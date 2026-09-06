from flask import Blueprint, render_template, request, session, flash, redirect, url_for, abort, send_file
from db import (
    get_all_pdfs, get_pdf_by_code, get_pdf_by_id, increment_pdf_view,
    get_pdf_distinct_subjects, get_pdf_distinct_classes, get_pdf_distinct_curricula
)
from services.tier_service import can_access_premium_resources
import os
from config import Config

pdfs_bp = Blueprint('pdfs', __name__, url_prefix='/pdfs')

@pdfs_bp.route('/')
def list_pdfs():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    subject_filter = request.args.get('subject', '')
    class_filter = request.args.get('class', '')
    curriculum_filter = request.args.get('curriculum', '')
    search_query = request.args.get('search', '').strip()

    pdfs = get_all_pdfs(
        limit=100,
        offset=0,
        search=search_query,
        subject=subject_filter,
        curriculum=curriculum_filter,
        class_filter=class_filter
    )

    can_access_premium = can_access_premium_resources()
    if not can_access_premium:
        pdfs = [p for p in pdfs if not p.get('is_premium', 0)]

    subjects = get_pdf_distinct_subjects()
    classes = get_pdf_distinct_classes()
    curricula = get_pdf_distinct_curricula()

    return render_template('dashboard/pdfs.html',
                         pdfs=pdfs,
                         subjects=subjects,
                         classes=classes,
                         curricula=curricula,
                         subject_filter=subject_filter,
                         class_filter=class_filter,
                         curriculum_filter=curriculum_filter,
                         search_query=search_query)

@pdfs_bp.route('/view/<pdf_id>')
def view_pdf(pdf_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    pdf = get_pdf_by_id(pdf_id)
    if not pdf:
        flash('PDF not found.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))

    if pdf.get('is_premium', 0) and not can_access_premium_resources():
        flash('This is a premium resource. Upgrade to access it.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))

    increment_pdf_view(pdf_id)
    return render_template('dashboard/pdf_view.html', pdf=pdf)

@pdfs_bp.route('/download/<pdf_id>')
def download_pdf(pdf_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    pdf = get_pdf_by_id(pdf_id)
    if not pdf:
        abort(404)

    if pdf.get('is_premium', 0) and not can_access_premium_resources():
        flash('This is a premium resource. Upgrade to access it.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))

    if pdf.get('file_url'):
        file_path = pdf['file_url']
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=pdf.get('title', 'document.pdf'))
        else:
            return redirect(pdf['file_url'])

    return redirect(url_for('pdfs.telegram_download', code=pdf['code']))

@pdfs_bp.route('/telegram/<code>')
def telegram_download(code):
    pdf = get_pdf_by_code(code)
    if not pdf:
        flash('PDF not found.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))

    bot_username = Config.TELEGRAM_BOT_USERNAME or 'nuunplatform_bot'
    telegram_link = f"https://t.me/{bot_username}?start={code}"

    return render_template('dashboard/telegram_download.html',
                         pdf=pdf, telegram_link=telegram_link)