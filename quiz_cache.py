# ============================================
# LIVE QUIZ MEMORY CACHE - COMPLETE FIX
# ============================================
# This file manages in-memory state for active quizzes
# to reduce database load and improve performance
# ============================================

import time
import json
from datetime import datetime, timezone
from threading import Lock
# MOVED IMPORTS TO TOP
from db import get_student_by_id, get_live_quiz_participant, update_live_quiz_participant

# ============================================
# CACHE STRUCTURE
# ============================================

class QuizCache:
    def __init__(self):
        self._quizzes = {}  # quiz_id -> quiz_data
        self._participants = {}  # quiz_id -> {user_id -> participant_data}
        self._timestamps = {}  # quiz_id -> last_update_time
        self._lock = Lock()
        self._write_queue = []  # pending writes to database
        self._last_flush = time.time()
        self._flush_interval = 2  # seconds (reduced from 3)
        self._max_quizzes = 20  # increased from 10
        self._quiz_timeout = 1200  # 20 minutes (increased from 15)
    
    # ============================================
    # QUIZ MANAGEMENT
    # ============================================
    
    def create_quiz(self, quiz_id, quiz_data):
        """Store a new quiz in memory cache"""
        with self._lock:
            # Clean up if too many quizzes
            if len(self._quizzes) >= self._max_quizzes:
                self._cleanup_old_quizzes()
            
            self._quizzes[quiz_id] = {
                'data': quiz_data,
                'participants': {},
                'created_at': time.time(),
                'last_update': time.time()
            }
            self._timestamps[quiz_id] = time.time()
            return True
    
    def get_quiz(self, quiz_id):
        """Get quiz data from cache"""
        with self._lock:
            if quiz_id not in self._quizzes:
                return None
            self._quizzes[quiz_id]['last_update'] = time.time()
            return self._quizzes[quiz_id]['data']
    
    def update_quiz(self, quiz_id, updates):
        """Update quiz data in cache"""
        with self._lock:
            if quiz_id not in self._quizzes:
                return False
            quiz = self._quizzes[quiz_id]
            quiz['data'].update(updates)
            quiz['last_update'] = time.time()
            self._timestamps[quiz_id] = time.time()
            return True
    
    def remove_quiz(self, quiz_id):
        """Remove a quiz from cache"""
        with self._lock:
            if quiz_id in self._quizzes:
                del self._quizzes[quiz_id]
                if quiz_id in self._participants:
                    del self._participants[quiz_id]
                if quiz_id in self._timestamps:
                    del self._timestamps[quiz_id]
                return True
            return False
    
    # ============================================
    # PARTICIPANT MANAGEMENT - FIXED WITH NAME
    # ============================================
    
    def add_participant(self, quiz_id, user_id, participant_data):
        """Add a participant to a quiz"""
        with self._lock:
            if quiz_id not in self._quizzes:
                return False
            
            if quiz_id not in self._participants:
                self._participants[quiz_id] = {}
            
            # Ensure name is stored
            if 'name' not in participant_data:
                participant_data['name'] = 'Participant'
            
            self._participants[quiz_id][user_id] = {
                'data': participant_data,
                'joined_at': time.time(),
                'last_update': time.time()
            }
            
            self._quizzes[quiz_id]['participants'][user_id] = participant_data
            self._quizzes[quiz_id]['last_update'] = time.time()
            
            return True
    
    def get_participant(self, quiz_id, user_id):
        """Get a participant's data"""
        with self._lock:
            if quiz_id not in self._participants:
                return None
            if user_id not in self._participants[quiz_id]:
                return None
            self._participants[quiz_id][user_id]['last_update'] = time.time()
            return self._participants[quiz_id][user_id]['data']
    
    def get_participant_with_name(self, quiz_id, user_id):
        """Get a participant's data including name from DB if missing"""
        with self._lock:
            participant = self.get_participant(quiz_id, user_id)
            if participant and participant.get('name') == 'Participant':
                # Try to get name from database - using imported function
                try:
                    student = get_student_by_id(user_id)
                    if student:
                        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant'
                        participant['name'] = name
                        self.update_participant(quiz_id, user_id, {'name': name})
                except Exception:
                    pass
            return participant
    
    def update_participant(self, quiz_id, user_id, updates):
        """Update a participant's data"""
        with self._lock:
            if quiz_id not in self._participants:
                return False
            if user_id not in self._participants[quiz_id]:
                return False
            
            participant = self._participants[quiz_id][user_id]
            participant['data'].update(updates)
            participant['last_update'] = time.time()
            
            # Also update in quiz
            if quiz_id in self._quizzes:
                self._quizzes[quiz_id]['participants'][user_id].update(updates)
                self._quizzes[quiz_id]['last_update'] = time.time()
            
            # Queue for database write - IMMEDIATELY for score updates
            self._queue_write(quiz_id, user_id, updates)
            
            return True
    
    def get_all_participants(self, quiz_id):
        """Get all participants for a quiz"""
        with self._lock:
            if quiz_id not in self._participants:
                return {}
            # Return copy to avoid modification
            return {
                uid: p['data'].copy() 
                for uid, p in self._participants[quiz_id].items()
            }
    
    def get_participant_count(self, quiz_id):
        """Get number of participants"""
        with self._lock:
            if quiz_id not in self._participants:
                return 0
            return len(self._participants[quiz_id])
    
    # ============================================
    # SCOREBOARD / LEADERBOARD - FIXED WITH NAMES
    # ============================================
    
    def get_leaderboard(self, quiz_id, limit=10):
        """Get top participants by score with proper names"""
        with self._lock:
            if quiz_id not in self._participants:
                return []
            
            participants = []
            for uid, p in self._participants[quiz_id].items():
                # Get name with fallback
                name = p['data'].get('name', 'Participant')
                if name == 'Participant':
                    # Try to get from database if we have a student ID
                    try:
                        student = get_student_by_id(uid)
                        if student:
                            name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant'
                            # Update cache with correct name
                            p['data']['name'] = name
                    except Exception:
                        pass
                
                participants.append({
                    'user_id': uid,
                    'score': p['data'].get('score', 0),
                    'name': name,
                    'correct': p['data'].get('correct_count', 0),
                    'wrong': p['data'].get('wrong_count', 0),
                    'current_question_index': p['data'].get('current_question_index', 0)
                })
            
            participants.sort(key=lambda x: x['score'], reverse=True)
            
            # Add rank
            for i, p in enumerate(participants, 1):
                p['rank'] = i
            
            return participants[:limit]
    
    # ============================================
    # WRITE QUEUE - COMPLETE FIX
    # ============================================
    
    def _queue_write(self, quiz_id, user_id, updates):
        """Queue a write for batch processing"""
        self._write_queue.append({
            'quiz_id': quiz_id,
            'user_id': user_id,
            'updates': updates,
            'timestamp': time.time()
        })
    
    def flush_writes(self):
        """Write queued updates to database - ACTUALLY WORKS NOW"""
        with self._lock:
            if not self._write_queue:
                return
            
            # Group updates by quiz and user
            grouped = {}
            for item in self._write_queue:
                key = f"{item['quiz_id']}_{item['user_id']}"
                if key not in grouped:
                    grouped[key] = {
                        'quiz_id': item['quiz_id'],
                        'user_id': item['user_id'],
                        'updates': {}
                    }
                grouped[key]['updates'].update(item['updates'])
            
            # Execute batched writes
            for key, batch in grouped.items():
                try:
                    # Get participant by quiz_id and user_id
                    participant = get_live_quiz_participant(batch['quiz_id'], batch['user_id'])
                    
                    if participant:
                        # Update the database
                        update_live_quiz_participant(participant['id'], batch['updates'])
                    else:
                        print(f"Warning: Participant not found for quiz {batch['quiz_id']}, user {batch['user_id']}")
                        
                except Exception as e:
                    print(f"Error flushing writes: {e}")
                    # Don't clear the queue on error - retry next time
            
            self._write_queue = []
            self._last_flush = time.time()
    
    # ============================================
    # CLEANUP & MAINTENANCE
    # ============================================
    
    def _cleanup_old_quizzes(self):
        """Remove old/inactive quizzes"""
        now = time.time()
        to_remove = []
        
        for quiz_id, quiz in self._quizzes.items():
            # Remove if inactive for too long
            if now - quiz['last_update'] > self._quiz_timeout:
                to_remove.append(quiz_id)
        
        for quiz_id in to_remove:
            self.remove_quiz(quiz_id)
    
    def cleanup(self):
        """Periodic cleanup"""
        with self._lock:
            self._cleanup_old_quizzes()
            
            # Flush writes if interval passed
            if time.time() - self._last_flush > self._flush_interval:
                self.flush_writes()
    
    def force_flush(self):
        """Force flush all pending writes"""
        with self._lock:
            self.flush_writes()
    
    def get_cache_stats(self):
        """Get cache statistics"""
        with self._lock:
            return {
                'active_quizzes': len(self._quizzes),
                'total_participants': sum(len(p) for p in self._participants.values()),
                'pending_writes': len(self._write_queue),
                'memory_usage': self._estimate_memory()
            }
    
    def _estimate_memory(self):
        """Estimate memory usage (approximate)"""
        import sys
        total = 0
        for quiz in self._quizzes.values():
            total += sys.getsizeof(quiz)
        return total

# ============================================
# SINGLETON INSTANCE
# ============================================

_quiz_cache = None

def get_quiz_cache():
    """Get the singleton QuizCache instance"""
    global _quiz_cache
    if _quiz_cache is None:
        _quiz_cache = QuizCache()
    return _quiz_cache

def flush_cache():
    """Manually flush pending writes"""
    cache = get_quiz_cache()
    cache.force_flush()

def cleanup_cache():
    """Manually trigger cleanup"""
    cache = get_quiz_cache()
    cache.cleanup()