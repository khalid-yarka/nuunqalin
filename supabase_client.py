from supabase import create_client, Client
from config import Config
import secrets
import string

# Initialize Supabase client
supabase: Client = create_client(
    Config.SUPABASE_URL,
    Config.SUPABASE_KEY
)

# Character set for public_id (A-Z + 1-9, excluding 0)
PUBLIC_ID_CHARS = string.ascii_uppercase + '123456789'
PUBLIC_ID_LENGTH = 4


def generate_public_id() -> str:
    """Generate a unique 4-character alphanumeric public ID"""
    return ''.join(secrets.choice(PUBLIC_ID_CHARS) for _ in range(PUBLIC_ID_LENGTH))


# ============================================
# STUDENT FUNCTIONS
# ============================================

def get_student_by_phone(phone: str):
    """Get student by phone number"""
    try:
        response = supabase.table('students')\
            .select('*')\
            .eq('phone_number', phone)\
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching student: {e}")
        return None


def get_student_by_id(student_id: str):
    """Get student by internal UUID"""
    try:
        response = supabase.table('students')\
            .select('*')\
            .eq('id', student_id)\
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching student: {e}")
        return None


def get_student_by_public_id(public_id: str):
    """Get student by public ID"""
    try:
        response = supabase.table('students')\
            .select('*')\
            .eq('public_id', public_id)\
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching student: {e}")
        return None


def create_student(data: dict):
    """Create a new student with auto-generated public_id"""
    try:
        public_id = generate_public_id()
        while get_student_by_public_id(public_id):
            public_id = generate_public_id()
        data['public_id'] = public_id
        data['is_admin'] = False
        
        response = supabase.table('students').insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating student: {e}")
        return None


def update_student_points(student_id: str, points: int):
    """Update student's total points"""
    try:
        response = supabase.table('students')\
            .update({'total_points': points})\
            .eq('id', student_id)\
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating points: {e}")
        return None


def is_admin(user_id: str) -> bool:
    """Check if a user is an admin"""
    try:
        response = supabase.table('students')\
            .select('is_admin')\
            .eq('id', user_id)\
            .execute()
        if response.data:
            return response.data[0].get('is_admin', False)
        return False
    except Exception as e:
        print(f"Error checking admin: {e}")
        return False


def toggle_admin(user_id: str) -> bool:
    """Toggle admin status for a user"""
    try:
        current = supabase.table('students')\
            .select('is_admin')\
            .eq('id', user_id)\
            .execute()
        
        if not current.data:
            return False
        
        new_status = not current.data[0].get('is_admin', False)
        
        response = supabase.table('students')\
            .update({'is_admin': new_status})\
            .eq('id', user_id)\
            .execute()
        
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error toggling admin: {e}")
        return None


def get_all_students():
    """Get all students (admin only)"""
    try:
        response = supabase.table('students')\
            .select('id, public_id, first_name, last_name, phone_number, location, school, grade, total_points, is_admin, created_at')\
            .order('created_at', desc=True)\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching students: {e}")
        return []


def get_schools_by_location(location: str):
    """Get schools by location"""
    try:
        response = supabase.table('schools')\
            .select('*')\
            .eq('location', location)\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching schools: {e}")
        return []


# ============================================
# SUBJECT FUNCTIONS
# ============================================

def get_all_subjects():
    """Get all subjects"""
    try:
        response = supabase.table('subjects')\
            .select('*')\
            .order('name')\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching subjects: {e}")
        return []


def get_subject_by_id(subject_id: str):
    """Get subject by ID"""
    try:
        response = supabase.table('subjects')\
            .select('*')\
            .eq('id', subject_id)\
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching subject: {e}")
        return None


def create_subject(data: dict):
    """Create a new subject"""
    try:
        response = supabase.table('subjects').insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating subject: {e}")
        return None


def delete_subject(subject_id: str):
    """Delete a subject"""
    try:
        response = supabase.table('subjects').delete().eq('id', subject_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error deleting subject: {e}")
        return None


# ============================================
# QUESTION FUNCTIONS
# ============================================

def get_questions_by_subject(subject_id: str, limit: int = 10):
    """Get random questions for a subject"""
    try:
        response = supabase.table('questions')\
            .select('*')\
            .eq('subject_id', subject_id)\
            .execute()
        
        import random
        questions = response.data if response.data else []
        if len(questions) > limit:
            return random.sample(questions, limit)
        return questions
    except Exception as e:
        print(f"Error fetching questions: {e}")
        return []


def get_all_questions():
    """Get all questions (admin only)"""
    try:
        response = supabase.table('questions')\
            .select('*, subjects(name)')\
            .order('created_at', desc=True)\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching questions: {e}")
        return []


def create_question(data: dict):
    """Create a new question"""
    try:
        response = supabase.table('questions').insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating question: {e}")
        return None


def update_question(question_id: str, data: dict):
    """Update a question"""
    try:
        response = supabase.table('questions')\
            .update(data)\
            .eq('id', question_id)\
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating question: {e}")
        return None


def delete_question(question_id: str):
    """Delete a question"""
    try:
        response = supabase.table('questions').delete().eq('id', question_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error deleting question: {e}")
        return None


# ============================================
# QUIZ ATTEMPT FUNCTIONS (FIXED)
# ============================================

def save_quiz_attempt(student_id: str, subject_id: str, score: int, total: int, answers: list, ratings: list):
    """Save a quiz attempt"""
    try:
        data = {
            'student_id': student_id,
            'subject_id': subject_id,
            'score': score,
            'total_questions': total,
            'answers': answers,
            'ratings': ratings,
            'completed_at': 'now()'
        }
        response = supabase.table('quiz_attempts').insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error saving quiz attempt: {e}")
        return None


def get_user_quiz_history(student_id: str, limit: int = 10):
    """Get user's quiz history"""
    try:
        response = supabase.table('quiz_attempts')\
            .select('*, subjects(name)')\
            .eq('student_id', student_id)\
            .order('completed_at', desc=True)\
            .limit(limit)\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching quiz history: {e}")
        return []


def get_leaderboard(limit: int = 20):
    """Get global leaderboard"""
    try:
        response = supabase.table('students')\
            .select('public_id, first_name, last_name, total_points, school')\
            .order('total_points', desc=True)\
            .limit(limit)\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching leaderboard: {e}")
        return []

# ============================================
# DELETED USERS / RECOVERY FUNCTIONS
# ============================================

def delete_user(student_id: str, admin_id: str, keep_ratings: bool = True, delete_attempts: bool = True):
    """Delete a user and backup their data"""
    try:
        # Get user data first
        user = get_student_by_id(student_id)
        if not user:
            return None, 'User not found'
        
        # Don't allow deleting yourself
        if student_id == admin_id:
            return None, 'You cannot delete your own account'
        
        # Backup user data to deleted_users table
        backup_data = {
            'original_id': user['id'],
            'public_id': user.get('public_id'),
            'first_name': user.get('first_name'),
            'last_name': user.get('last_name'),
            'phone_number': user.get('phone_number'),
            'school': user.get('school'),
            'grade': user.get('grade'),
            'total_points': user.get('total_points', 0),
            'is_admin': user.get('is_admin', False),
            'location': user.get('location'),
            'city': user.get('city'),
            'deleted_by': admin_id,
            'data': user  # Full backup as JSON
        }
        
        supabase.table('deleted_users').insert(backup_data).execute()
        
        # Delete quiz attempts if requested
        if delete_attempts:
            supabase.table('quiz_attempts').delete().eq('student_id', student_id).execute()
        
        # Delete ratings if NOT keeping them
        if not keep_ratings:
            supabase.table('quiz_ratings').delete().eq('student_id', student_id).execute()
        
        # Delete the user
        supabase.table('students').delete().eq('id', student_id).execute()
        
        return True, 'User deleted successfully'
        
    except Exception as e:
        print(f"Error deleting user: {e}")
        return False, str(e)


def get_deleted_users(limit: int = 50):
    """Get list of deleted users for admin recovery"""
    try:
        response = supabase.table('deleted_users')\
            .select('*, deleted_by_data:students(first_name, last_name, public_id)')\
            .order('deleted_at', desc=True)\
            .limit(limit)\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching deleted users: {e}")
        return []


def restore_deleted_user(deleted_id: str):
    """Restore a deleted user from backup"""
    try:
        # Get backup data
        response = supabase.table('deleted_users')\
            .select('*')\
            .eq('id', deleted_id)\
            .execute()
        
        if not response.data:
            return False, 'Deleted user not found'
        
        backup = response.data[0]
        user_data = backup.get('data', {})
        
        # Remove id to let Supabase generate new one
        user_data.pop('id', None)
        user_data.pop('created_at', None)
        
        # Re-insert user
        result = supabase.table('students').insert(user_data).execute()
        
        if result.data:
            # Remove from deleted_users
            supabase.table('deleted_users').delete().eq('id', deleted_id).execute()
            return True, 'User restored successfully'
        
        return False, 'Failed to restore user'
        
    except Exception as e:
        print(f"Error restoring user: {e}")
        return False, str(e)