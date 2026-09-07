# blueprints/history_bp.py

import csv
import json
from io import StringIO
from flask import Blueprint, request, session, jsonify, Response, abort, render_template
from functools import wraps
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from db import execute_with_retry
from utils import get_somali_time_db
from services.tier_service import (
    get_history_retention_days,
    get_history_max_entries,
    can_search_history,
    can_export_history,
    can_see_trends,
    can_delete_history,
    get_current_user_tier,
    get_feature_level
)

history_bp = Blueprint('history', __name__, url_prefix='/history')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            abort(401)
        return f(*args, **kwargs)
    return decorated


def validate_date(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.isoformat()
    except ValueError:
        return None


@history_bp.route('')
@login_required
def index():
    """Render the history page."""
    user_id = session['user_id']
    tier = get_current_user_tier()
    can_search = can_search_history(user_id)
    can_export = can_export_history(user_id)
    can_trend = can_see_trends(user_id)
    can_delete = can_delete_history(user_id)

    # Basic stats for the UI
    stats = get_history_stats(user_id)

    return render_template(
        'dashboard/history.html',
        tier=tier,
        can_search=can_search,
        can_export=can_export,
        can_trend=can_trend,
        can_delete=can_delete,
        stats=stats
    )


@history_bp.route('/api/entries')
@login_required
def get_entries():
    """
    GET /history/api/entries?types=quiz_attempt,live_quiz&start_date=...&end_date=...&search=...&page=1&per_page=20&order=desc
    Returns paginated history entries.
    """
    user_id = session['user_id']
    tier = get_current_user_tier()

    # Parse parameters
    types_param = request.args.get('types', '')
    if types_param:
        types = [t.strip() for t in types_param.split(',') if t.strip()]
    else:
        types = None

    start_date = validate_date(request.args.get('start_date'))
    end_date = validate_date(request.args.get('end_date'))
    search = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    order = request.args.get('order', 'desc').lower()
    if order not in ('asc', 'desc'):
        order = 'desc'

    # Apply tier restrictions
    max_per_page = 20 if tier == 'danbe' else 50 if tier == 'dhexe' else 100
    if per_page > max_per_page:
        per_page = max_per_page

    # Date range restrictions
    if tier == 'danbe':
        # Last 7 days
        if not start_date or not end_date:
            end_date = get_somali_time_db()
            start_date = (datetime.now() - timedelta(days=7)).isoformat()
        else:
            # Ensure range does not exceed 7 days
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            if (end_dt - start_dt).days > 7:
                start_date = (end_dt - timedelta(days=7)).isoformat()
    elif tier == 'dhexe':
        # Last 30 days
        if not start_date or not end_date:
            end_date = get_somali_time_db()
            start_date = (datetime.now() - timedelta(days=30)).isoformat()
        else:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            if (end_dt - start_dt).days > 30:
                start_date = (end_dt - timedelta(days=30)).isoformat()

    # Search only allowed for Hore
    if search and not can_search_history(user_id):
        return jsonify({'error': 'Search is not available for your tier.'}), 403

    # Build query
    query = """
        SELECT id, user_id, entry_type, action, entry_id, metadata, created_at
        FROM history_entries
        WHERE user_id = ?
    """
    count_query = "SELECT COUNT(*) as total FROM history_entries WHERE user_id = ?"
    params = [user_id]
    count_params = [user_id]

    if types:
        placeholders = ','.join('?' for _ in types)
        query += f" AND entry_type IN ({placeholders})"
        count_query += f" AND entry_type IN ({placeholders})"
        params.extend(types)
        count_params.extend(types)

    if start_date:
        query += " AND created_at >= ?"
        count_query += " AND created_at >= ?"
        params.append(start_date)
        count_params.append(start_date)

    if end_date:
        query += " AND created_at <= ?"
        count_query += " AND created_at <= ?"
        params.append(end_date)
        count_params.append(end_date)

    if search and can_search_history(user_id):
        # Search in metadata JSON (subject, title, etc.)
        query += " AND (metadata LIKE ?)"
        count_query += " AND (metadata LIKE ?)"
        like = f'%{search}%'
        params.append(like)
        count_params.append(like)

    # Order and pagination
    query += f" ORDER BY created_at {order} LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    # Execute queries
    entries_cursor = execute_with_retry(query, params)
    entries = [dict(row) for row in entries_cursor.fetchall()]

    count_cursor = execute_with_retry(count_query, count_params)
    total = count_cursor.fetchone()['total']

    return jsonify({
        'entries': entries,
        'pagination': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page if total > 0 else 1
        }
    })


@history_bp.route('/api/stats')
@login_required
def get_stats():
    """Return summary statistics for the user's history."""
    user_id = session['user_id']
    stats = get_history_stats(user_id)
    return jsonify(stats)


@history_bp.route('/api/export')
@login_required
def export():
    """
    Export filtered history as CSV.
    Tier: Dhexe limited to 100 rows, Hore unlimited.
    """
    user_id = session['user_id']
    if not can_export_history(user_id):
        return jsonify({'error': 'Export not available for your tier.'}), 403

    # Same filters as get_entries, but we want all rows (or limited)
    types_param = request.args.get('types', '')
    types = [t.strip() for t in types_param.split(',') if t.strip()] if types_param else None
    start_date = validate_date(request.args.get('start_date'))
    end_date = validate_date(request.args.get('end_date'))
    search = request.args.get('search', '').strip()
    order = request.args.get('order', 'desc').lower()

    # Tier limits
    tier = get_current_user_tier()
    limit = 100 if tier == 'dhexe' else None  # None = unlimited

    query = """
        SELECT id, entry_type, action, metadata, created_at
        FROM history_entries
        WHERE user_id = ?
    """
    params = [user_id]

    if types:
        placeholders = ','.join('?' for _ in types)
        query += f" AND entry_type IN ({placeholders})"
        params.extend(types)

    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date)

    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date)

    if search and can_search_history(user_id):
        query += " AND metadata LIKE ?"
        params.append(f'%{search}%')

    query += f" ORDER BY created_at {order}"
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cursor = execute_with_retry(query, params)
    entries = cursor.fetchall()

    # Build CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Type', 'Action', 'Metadata', 'Created At'])
    for row in entries:
        writer.writerow([
            row['id'],
            row['entry_type'],
            row['action'],
            row['metadata'],
            row['created_at']
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=history_export.csv'}
    )


@history_bp.route('/api/trends')
@login_required
def trends():
    """
    Return trend data for charts (Hore only).
    """
    user_id = session['user_id']
    if not can_see_trends(user_id):
        return jsonify({'error': 'Trends not available for your tier.'}), 403

    # Get quiz attempt scores over time (last 30 entries)
    query = """
        SELECT
            strftime('%Y-%m-%d', created_at) as date,
            json_extract(metadata, '$.percentage') as percentage,
            json_extract(metadata, '$.subject') as subject
        FROM history_entries
        WHERE user_id = ? AND entry_type = 'quiz_attempt'
        ORDER BY created_at DESC
        LIMIT 30
    """
    cursor = execute_with_retry(query, (user_id,))
    rows = cursor.fetchall()
    trend_data = [
        {
            'date': row['date'],
            'percentage': float(row['percentage']) if row['percentage'] is not None else 0,
            'subject': row['subject'] or 'Unknown'
        }
        for row in rows
    ]
    # Reverse to chronological order
    trend_data.reverse()
    return jsonify(trend_data)


def get_history_stats(user_id: int) -> Dict:
    """Helper to compute stats."""
    cursor = execute_with_retry("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN entry_type = 'quiz_attempt' THEN 1 END) as quizzes,
            COUNT(CASE WHEN entry_type = 'live_quiz' THEN 1 END) as live_quizzes,
            COUNT(CASE WHEN entry_type = 'achievement' THEN 1 END) as achievements,
            COUNT(CASE WHEN entry_type = 'save' THEN 1 END) as saves,
            COUNT(CASE WHEN entry_type = 'pdf_view' THEN 1 END) as pdf_views,
            AVG(CAST(json_extract(metadata, '$.percentage') AS REAL)) as avg_score
        FROM history_entries
        WHERE user_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    stats = dict(row)
    stats['avg_score'] = round(stats['avg_score'] or 0, 1)
    return stats