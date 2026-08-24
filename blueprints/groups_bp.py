from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from db import get_active_groups, get_group_categories, search_groups, track_group_click

groups_bp = Blueprint('groups', __name__, url_prefix='/groups')

@groups_bp.route('/')
def list_groups():
    """Display all active groups"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    platform_filter = request.args.get('platform', '')
    category_filter = request.args.get('category', '')
    search_query = request.args.get('search', '').strip()
    
    groups = search_groups(search_query, platform_filter, category_filter)
    categories = get_group_categories()
    
    return render_template('dashboard/groups.html', 
                         groups=groups, 
                         categories=categories,
                         platform_filter=platform_filter,
                         category_filter=category_filter,
                         search_query=search_query)

@groups_bp.route('/track-click/<group_id>', methods=['POST'])
def track_group_click_route(group_id):
    """Track when a user clicks the Join button"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    success = track_group_click(group_id)
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to track click'}), 500