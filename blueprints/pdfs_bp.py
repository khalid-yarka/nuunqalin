from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from supabase_client import supabase

pdfs_bp = Blueprint('pdfs', __name__, url_prefix='/pdfs')


@pdfs_bp.route('/')
def list_pdfs():
    """Display all PDFs"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    # Get filters
    subject_filter = request.args.get('subject', '')
    grade_filter = request.args.get('grade', '')
    search_query = request.args.get('search', '').strip()
    
    # Build query
    query = supabase.table('pdfs').select('*')
    
    if subject_filter:
        query = query.eq('subject', subject_filter)
    
    if grade_filter:
        query = query.eq('grade', grade_filter)
    
    if search_query:
        query = query.ilike('title', f'%{search_query}%')
    
    # Get PDFs
    try:
        response = query.order('created_at', desc=True).execute()
        pdfs = response.data if response.data else []
    except Exception as e:
        print(f"Error fetching PDFs: {e}")
        pdfs = []
        flash('Error loading PDFs. Please try again.', 'error')
    
    # Get distinct subjects for filter
    try:
        subject_response = supabase.table('pdfs').select('subject').execute()
        subjects = list(set([p.get('subject') for p in subject_response.data if p.get('subject')]))
    except Exception:
        subjects = []
    
    # Get distinct grades for filter
    try:
        grade_response = supabase.table('pdfs').select('grade').execute()
        grades = list(set([p.get('grade') for p in grade_response.data if p.get('grade')]))
    except Exception:
        grades = []
    
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
    
    # Get PDF
    try:
        response = supabase.table('pdfs').select('*').eq('id', pdf_id).execute()
        if not response.data:
            flash('PDF not found.', 'error')
            return redirect(url_for('pdfs.list_pdfs'))
        
        pdf = response.data[0]
        
        # Increment view count
        supabase.table('pdfs')\
            .update({'view_count': pdf.get('view_count', 0) + 1})\
            .eq('id', pdf_id)\
            .execute()
        
        return render_template('dashboard/pdf_view.html', pdf=pdf)
        
    except Exception as e:
        print(f"Error viewing PDF: {e}")
        flash('Error loading PDF. Please try again.', 'error')
        return redirect(url_for('pdfs.list_pdfs'))