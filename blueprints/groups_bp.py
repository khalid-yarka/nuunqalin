from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from supabase_client import supabase

groups_bp = Blueprint('groups', __name__, url_prefix='/groups')


@groups_bp.route('/')
def list_groups():
    """Display all active groups"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    # Get platform filter from query string
    platform_filter = request.args.get('platform', '')
    category_filter = request.args.get('category', '')
    search_query = request.args.get('search', '').strip()
    
    # Build query
    query = supabase.table('groups').select('*').eq('is_active', True)
    
    if platform_filter:
        query = query.eq('platform', platform_filter)
    
    if category_filter:
        query = query.eq('category', category_filter)
    
    if search_query:
        query = query.ilike('name', f'%{search_query}%')
    
    # Get groups
    try:
        response = query.order('created_at', desc=True).execute()
        groups = response.data if response.data else []
    except Exception as e:
        print(f"Error fetching groups: {e}")
        groups = []
        flash('Error loading groups. Please try again.', 'error')
    
    # Get distinct categories for filter
    try:
        cat_response = supabase.table('groups')\
            .select('category')\
            .eq('is_active', True)\
            .execute()
        categories = list(set([g.get('category') for g in cat_response.data if g.get('category')]))
    except Exception:
        categories = []
    
    return render_template('dashboard/groups.html', 
                         groups=groups, 
                         categories=categories,
                         platform_filter=platform_filter,
                         category_filter=category_filter,
                         search_query=search_query)