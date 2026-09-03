from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, abort, send_file
from db import search_pdfs, get_pdf_by_id, get_pdf_distinct_subjects, get_pdf_distinct_grades, increment_pdf_view
from services.tier_service import (
    can_access_premium_resources,
    get_resource_downloads_remaining,
    check_and_consume_quota,
    get_feature_level,
    get_current_user_tier,
)
import os
from config import Config

pdfs_bp = Blueprint('pdfs', __name__, url_prefix='/pdfs')

@pdfs_bp.route('/')
def list_pdfs():
    """Display all PDFs"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    tier = get_current_user_tier()
    
    # --- TIER CHECK: Resource Search ---
    search_level = get_feature_level("resource_search", user_id)
    
    # Get filters
    subject_filter = request.args.get('subject', '')
    grade_filter = request.args.get('grade', '')
    search_query = request.args.get('search', '').strip()
    
    # If Danbe and search query present, block
    if search_level == 0 and search_query:
        flash('Search is locked for Safka Danbe. Upgrade to Safka Dhexe or Safka Hore to search.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))
    
    # For Danbe, we still allow browsing without search
    pdfs = search_pdfs(search_query if search_level > 0 else '', subject_filter if search_level >= 1 else '', grade_filter if search_level >= 2 else '')
    
    # --- TIER CHECK: Premium Resources ---
    can_access_premium = can_access_premium_resources()
    if not can_access_premium:
        # Filter out premium PDFs
        pdfs = [p for p in pdfs if not p.get('is_premium', 0)]
    
    subjects = get_pdf_distinct_subjects() if search_level >= 1 else []
    grades = get_pdf_distinct_grades() if search_level >= 2 else []
    
    # Get download quota info
    remaining_downloads = get_resource_downloads_remaining(user_id)
    
    return render_template('dashboard/pdfs.html',
                         pdfs=pdfs,
                         subjects=subjects,
                         grades=grades,
                         subject_filter=subject_filter if search_level >= 1 else '',
                         grade_filter=grade_filter if search_level >= 2 else '',
                         search_query=search_query if search_level > 0 else '',
                         search_level=search_level,
                         remaining_downloads=remaining_downloads,
                         tier=tier)

@pdfs_bp.route('/view/<pdf_id>')
def view_pdf(pdf_id):
    """View a specific PDF"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    pdf = get_pdf_by_id(pdf_id)
    if not pdf:
        flash('PDF not found.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))
    
    # --- TIER CHECK: Premium Resources ---
    if pdf.get('is_premium', 0) and not can_access_premium_resources():
        flash('This is a premium resource. Upgrade to Safka Dhexe or Safka Hore to view it.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))
    
    increment_pdf_view(pdf_id)
    return render_template('dashboard/pdf_view.html', pdf=pdf)

@pdfs_bp.route('/download/<pdf_id>')
def download_pdf(pdf_id):
    """Download a PDF – consumes download quota"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    pdf = get_pdf_by_id(pdf_id)
    if not pdf:
        abort(404)
    
    # --- TIER CHECK: Premium Resources ---
    if pdf.get('is_premium', 0) and not can_access_premium_resources():
        flash('This is a premium resource. Upgrade to Safka Dhexe or Safka Hore to download it.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))
    
    # --- QUOTA CHECK ---
    remaining = get_resource_downloads_remaining(user_id)
    if remaining <= 0:
        flash('You have used all your resource downloads for today. Come back tomorrow!', 'error')
        return redirect(url_for('pdfs.list_pdfs'))
    
    # Consume quota atomically
    if not check_and_consume_quota(user_id, 'resource_download'):
        flash('Failed to download. Please try again.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))
    
    # Redirect to the actual download URL (Telegram or file)
    # If the PDF has a telegram_download_url, use it; else serve file directly
    if pdf.get('telegram_download_url'):
        return redirect(pdf['telegram_download_url'])
    else:
        # Fallback: serve file if local
        file_path = os.path.join(Config.UPLOAD_FOLDER, pdf.get('file_url', ''))
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=pdf.get('title', 'document.pdf'))
        else:
            flash('Download file not found.', 'error')
            return redirect(url_for('pdfs.list_pdfs'))

# Add a route to get remaining downloads (for AJAX)
@pdfs_bp.route('/downloads-remaining')
def downloads_remaining():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    remaining = get_resource_downloads_remaining(session['user_id'])
    return jsonify({'remaining': remaining})