# redis_state.py
"""
Live Quiz Redis State Manager.
Provides atomic operations for participant state, leaderboard, and concurrency control.
"""

import json
import time
import logging
from typing import Optional, Dict, Any, List, Tuple

import redis

logger = logging.getLogger(__name__)

class LiveQuizState:
    """Manager for Redis-based Live Quiz state."""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.prefix = "livequiz:"

    def _key(self, *parts: str) -> str:
        return self.prefix + ":".join(parts)

    # --------------------------------------------
    #  Participant State (Hash)
    # --------------------------------------------
    def get_participant(self, quiz_id: int, user_id: int) -> Optional[Dict]:
        """Get participant state from Redis."""
        if not self.redis:
            return None
        key = self._key("participant", str(quiz_id), str(user_id))
        data = self.redis.hgetall(key)
        if not data:
            return None
        # Decode bytes to strings
        decoded = {k.decode('utf-8'): v.decode('utf-8') for k, v in data.items()}
        # Convert JSON fields
        if 'answers' in decoded:
            decoded['answers'] = json.loads(decoded['answers'])
        if 'ratings' in decoded:
            decoded['ratings'] = json.loads(decoded['ratings'])
        # Convert numeric fields
        for field in ['score', 'current_question_index', 'correct_count', 'wrong_count', 'skipped_count']:
            if field in decoded:
                decoded[field] = int(decoded[field])
        return decoded

    def update_participant(self, quiz_id: int, user_id: int, updates: Dict) -> bool:
        """Update participant state (non‑atomic)."""
        if not self.redis:
            return False
        key = self._key("participant", str(quiz_id), str(user_id))
        # Serialize JSON fields
        serialized = {}
        for k, v in updates.items():
            if k in ('answers', 'ratings'):
                serialized[k] = json.dumps(v)
            else:
                serialized[k] = str(v)
        self.redis.hset(key, mapping=serialized)
        # Set TTL (e.g., 1 hour for active quiz)
        self.redis.expire(key, 3600)
        return True

    def init_participant(self, quiz_id: int, user_id: int, question_ids: List[int],
                         initial_data: Optional[Dict] = None) -> bool:
        """Initialize a new participant or restore from checkpoint."""
        if not self.redis:
            return False
        if initial_data is None:
            initial_data = {
                'score': 0,
                'current_question_index': 0,
                'correct_count': 0,
                'wrong_count': 0,
                'skipped_count': 0,
                'answers': {},
                'ratings': {},
                'status': 'active',
                'is_ready': False,
                'name': 'Unknown'
            }
        # Include shuffled question IDs order
        if question_ids:
            import random
            shuffled = question_ids[:]
            random.shuffle(shuffled)
            if 'answers' not in initial_data:
                initial_data['answers'] = {}
            initial_data['answers']['__shuffled_ids'] = shuffled
        return self.update_participant(quiz_id, user_id, initial_data)

    # --------------------------------------------
    #  Atomic Answer Submission (using Lua)
    # --------------------------------------------
    SUBMIT_ANSWER_LUA = """
        local quiz_id = ARGV[1]
        local user_id = ARGV[2]
        local question_id = ARGV[3]
        local answer = ARGV[4]
        local correct_answer = ARGV[5]
        local key_prefix = 'livequiz:participant:' .. quiz_id .. ':' .. user_id

        -- Check if already answered this question
        local answers_json = redis.call('HGET', key_prefix, 'answers')
        local answers = {}
        if answers_json then
            answers = cjson.decode(answers_json)
        end
        if answers[question_id] then
            return {-1, 'already answered'}
        end

        -- Determine correctness
        local is_correct = (answer == correct_answer)
        local points = is_correct and 2 or 0

        -- Update score, counts
        local score = redis.call('HINCRBY', key_prefix, 'score', points)
        local correct_count = redis.call('HINCRBY', key_prefix, 'correct_count', is_correct and 1 or 0)
        local wrong_count = redis.call('HINCRBY', key_prefix, 'wrong_count', is_correct and 0 or 1)

        -- Store answer
        answers[question_id] = {answer = answer, correct = is_correct}
        redis.call('HSET', key_prefix, 'answers', cjson.encode(answers))

        -- Update leaderboard
        local lb_key = 'livequiz:leaderboard:' .. quiz_id
        redis.call('ZINCRBY', lb_key, points, user_id)

        -- Return result
        return {is_correct and 1 or 0, correct_answer}
    """

    def submit_answer(self, quiz_id: int, user_id: int, question_id: int,
                      answer: str, correct_answer: str) -> Tuple[bool, Dict]:
        """
        Atomically submit an answer.
        Returns (success, result_dict) where result_dict contains 'correct', 'correct_answer', 'explanation'.
        """
        if not self.redis:
            return False, {'error': 'Redis unavailable'}

        try:
            script = self.redis.register_script(self.SUBMIT_ANSWER_LUA)
            result = script(keys=[], args=[
                str(quiz_id), str(user_id), str(question_id),
                answer, correct_answer
            ])
            if result[0] == -1:
                return False, {'error': result[1]}
            is_correct = bool(result[0])
            correct_ans = result[1]
            from db import get_question_by_id
            q = get_question_by_id(question_id)
            explanation = q.get('explanation', '') if q else ''
            return True, {
                'correct': is_correct,
                'correct_answer': correct_ans,
                'explanation': explanation
            }
        except Exception as e:
            logger.error(f"Error in submit_answer Lua: {e}")
            return False, {'error': str(e)}

    # --------------------------------------------
    #  Skip Question (Lua)
    # --------------------------------------------
    SKIP_QUESTION_LUA = """
        local quiz_id = ARGV[1]
        local user_id = ARGV[2]
        local question_id = ARGV[3]
        local key_prefix = 'livequiz:participant:' .. quiz_id .. ':' .. user_id

        -- Check if already answered
        local answers_json = redis.call('HGET', key_prefix, 'answers')
        local answers = {}
        if answers_json then
            answers = cjson.decode(answers_json)
        end
        if answers[question_id] then
            return {-1, 'already answered'}
        end

        -- Store skip
        answers[question_id] = {answer = nil, correct = false, skipped = true}
        redis.call('HSET', key_prefix, 'answers', cjson.encode(answers))

        -- Increment skipped_count
        redis.call('HINCRBY', key_prefix, 'skipped_count', 1)

        -- Increment current_question_index
        local new_index = redis.call('HINCRBY', key_prefix, 'current_question_index', 1)

        return {1, new_index}
    """

    def skip_question(self, quiz_id: int, user_id: int, question_id: int) -> Tuple[bool, str]:
        if not self.redis:
            return False, 'Redis unavailable'
        try:
            script = self.redis.register_script(self.SKIP_QUESTION_LUA)
            result = script(keys=[], args=[str(quiz_id), str(user_id), str(question_id)])
            if result[0] == -1:
                return False, result[1]
            return True, 'skipped'
        except Exception as e:
            logger.error(f"Error in skip_question Lua: {e}")
            return False, str(e)

    # --------------------------------------------
    #  Submit Rating (Lua)
    # --------------------------------------------
    SUBMIT_RATING_LUA = """
        local quiz_id = ARGV[1]
        local user_id = ARGV[2]
        local question_id = ARGV[3]
        local rating = ARGV[4]
        local key_prefix = 'livequiz:participant:' .. quiz_id .. ':' .. user_id

        -- Check if already rated
        local ratings_json = redis.call('HGET', key_prefix, 'ratings')
        local ratings = {}
        if ratings_json then
            ratings = cjson.decode(ratings_json)
        end
        if ratings[question_id] then
            return {-1, 'already rated'}
        end

        -- Store rating
        ratings[question_id] = rating
        redis.call('HSET', key_prefix, 'ratings', cjson.encode(ratings))

        -- Increment current_question_index
        local new_index = redis.call('HINCRBY', key_prefix, 'current_question_index', 1)

        return {1, new_index}
    """

    def submit_rating(self, quiz_id: int, user_id: int, question_id: int, rating: str) -> Tuple[bool, str]:
        if not self.redis:
            return False, 'Redis unavailable'
        try:
            script = self.redis.register_script(self.SUBMIT_RATING_LUA)
            result = script(keys=[], args=[str(quiz_id), str(user_id), str(question_id), rating])
            if result[0] == -1:
                return False, result[1]
            return True, 'rated'
        except Exception as e:
            logger.error(f"Error in submit_rating Lua: {e}")
            return False, str(e)

    # --------------------------------------------
    #  Ready Status
    # --------------------------------------------
    def set_participant_ready(self, quiz_id: int, user_id: int, is_ready: bool) -> bool:
        return self.update_participant(quiz_id, user_id, {'is_ready': is_ready})

    # --------------------------------------------
    #  Get all participants for a quiz
    # --------------------------------------------
    def get_all_participants(self, quiz_id: int) -> List[Dict]:
        """Get all participants for a quiz from Redis (or DB fallback)."""
        if not self.redis:
            from db import get_live_quiz_participants_with_names
            return get_live_quiz_participants_with_names(quiz_id)
        pattern = self._key("participant", str(quiz_id), "*")
        participants = []
        cursor = 0
        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                parts = key.decode('utf-8').split(':')
                if len(parts) >= 4:
                    user_id = int(parts[-1])
                    p = self.get_participant(quiz_id, user_id)
                    if p:
                        p['user_id'] = user_id
                        if 'name' not in p:
                            from db import get_student_by_id
                            student = get_student_by_id(user_id)
                            p['name'] = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown'
                            p['public_id'] = student.get('public_id', '----')
                        participants.append(p)
            if cursor == 0:
                break
        return participants

    def get_active_participant_count(self, quiz_id: int) -> int:
        all_p = self.get_all_participants(quiz_id)
        return sum(1 for p in all_p if p.get('status') != 'left')

    # --------------------------------------------
    #  Leaderboard
    # --------------------------------------------
    def get_leaderboard(self, quiz_id: int, limit: int = 10) -> List[Dict]:
        if not self.redis:
            from db import get_live_quiz_participants_with_names
            parts = get_live_quiz_participants_with_names(quiz_id)
            sorted_parts = sorted(parts, key=lambda x: x.get('score', 0), reverse=True)
            return [{
                'user_id': p['student_id'],
                'name': f"{p.get('student', {}).get('first_name', '')} {p.get('student', {}).get('last_name', '')}".strip() or 'Unknown',
                'score': p.get('score', 0)
            } for p in sorted_parts[:limit]]
        lb_key = self._key("leaderboard", str(quiz_id))
        results = self.redis.zrevrange(lb_key, 0, limit-1, withscores=True)
        leaderboard = []
        for user_id_bytes, score in results:
            user_id = int(user_id_bytes.decode('utf-8'))
            p = self.get_participant(quiz_id, user_id)
            name = p.get('name', 'Unknown') if p else 'Unknown'
            leaderboard.append({
                'user_id': user_id,
                'name': name,
                'score': int(score)
            })
        return leaderboard

    def get_user_rank(self, quiz_id: int, user_id: int) -> Optional[int]:
        if not self.redis:
            from db import get_live_quiz_participants_with_names
            parts = get_live_quiz_participants_with_names(quiz_id)
            sorted_parts = sorted(parts, key=lambda x: x.get('score', 0), reverse=True)
            for i, p in enumerate(sorted_parts, 1):
                if p['student_id'] == user_id:
                    return i
            return None
        lb_key = self._key("leaderboard", str(quiz_id))
        rank = self.redis.zrevrank(lb_key, str(user_id))
        if rank is not None:
            return rank + 1
        return None

    # --------------------------------------------
    #  Quiz-level operations
    # --------------------------------------------
    def start_quiz(self, quiz_id: int) -> bool:
        """Initialize/reset all participants for active quiz."""
        from db import get_live_quiz_participants, get_question_ids_for_quiz
        participants = get_live_quiz_participants(quiz_id)
        question_ids = get_question_ids_for_quiz(quiz_id)
        for p in participants:
            self.init_participant(quiz_id, p['student_id'], question_ids, {
                'score': 0,
                'current_question_index': 0,
                'correct_count': 0,
                'wrong_count': 0,
                'skipped_count': 0,
                'answers': {},
                'ratings': {},
                'status': 'active',
                'is_ready': False
            })
            student = get_student_by_id(p['student_id'])
            if student:
                self.update_participant(quiz_id, p['student_id'], {
                    'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown',
                    'public_id': student.get('public_id', '----')
                })
        lb_key = self._key("leaderboard", str(quiz_id))
        self.redis.delete(lb_key)
        return True

    def delete_quiz(self, quiz_id: int) -> bool:
        """Delete all Redis keys for a quiz."""
        if not self.redis:
            return False
        pattern = self._key("participant", str(quiz_id), "*")
        keys = list(self.redis.scan_iter(match=pattern))
        if keys:
            self.redis.delete(*keys)
        lb_key = self._key("leaderboard", str(quiz_id))
        self.redis.delete(lb_key)
        return True

    # --------------------------------------------
    #  Checkpoint: save all participant state to DB
    # --------------------------------------------
    def checkpoint(self, quiz_id: int) -> bool:
        """Write current Redis state to SQLite (durable)."""
        participants = self.get_all_participants(quiz_id)
        if not participants:
            return False
        from db import update_live_quiz_participant, get_live_quiz_participant
        for p in participants:
            db_p = get_live_quiz_participant(quiz_id, p['user_id'])
            if db_p:
                update_data = {
                    'score': p.get('score', 0),
                    'current_question_index': p.get('current_question_index', 0),
                    'correct_count': p.get('correct_count', 0),
                    'wrong_count': p.get('wrong_count', 0),
                    'skipped_count': p.get('skipped_count', 0),
                    'answers': p.get('answers', {}),
                    'ratings': p.get('ratings', {}),
                    'status': p.get('status', 'active'),
                    'is_ready': p.get('is_ready', 0),
                }
                update_live_quiz_participant(db_p['id'], update_data)
        return True