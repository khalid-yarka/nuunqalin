from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from db import search_pdfs, get_pdf_by_id, get_pdf_distinct_subjects, get_pdf_distinct_grades, increment_pdf_view

pdfs_bp = Blueprint('pdfs', __name__, url_prefix='/pdfs')

@pdfs_bp.route('/')
def list_pdfs():
    """Display all PDFs"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    subject_filter = request.args.get('subject', '')
    grade_filter = request.args.get('grade', '')
    search_query = request.args.get('search', '').strip()
    
    pdfs = search_pdfs(search_query, subject_filter, grade_filter)
    subjects = get_pdf_distinct_subjects()
    grades = get_pdf_distinct_grades()
    
    return render_template('dashboard/pdfs.html', 
                         pdfs=pdfs, 
                         subjects=subjects,
                         grades=grades,
                         subject_filter=subject_filter,
                         grade_filter=grade_filter,
                         search_query=search_query)

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
    
    increment_pdf_view(pdf_id)
    return render_template('dashboard/pdf_view.html', pdf=pdf)