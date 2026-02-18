import os
import eventlet
from datetime import datetime
from models.schedule import Schedule
from database import db
from utils.ai_response import generate_answer

class AIService:
    def __init__(self):
        self.active_rooms = {}  # {room_id: {'background_ai_sid': sid, 'proxies': {user_id: sid}}}
        self.absence_timers = {} # {room_id: {user_id: timer}}

    def start_absence_timer(self, room_id, user_id, user_name, user_role, socketio_emit_fn):
        """Starts a timer for a scheduled user. If they don't join, AI takes over."""
        timer_key = f"{room_id}_{user_id}"
        if timer_key in self.absence_timers:
            return

        print(f"[AI] Starting 2-min absence timer for {user_name} (ID: {user_id}) in room {room_id}")
        
        def on_timeout():
            print(f"[AI] User {user_name} is absent. AI Proxy taking over...")
            socketio_emit_fn('proxy_joined', {
                'name': user_name,
                'user_id': user_id,
                'role': 'proxy',
                'original_role': user_role
            }, room=room_id)
            del self.absence_timers[timer_key]

        timer = eventlet.spawn_after(120, on_timeout)
        self.absence_timers[timer_key] = timer

    def cancel_absence_timer(self, room_id, user_id):
        timer_key = f"{room_id}_{user_id}"
        if timer_key in self.absence_timers:
            print(f"[AI] User {user_id} joined room {room_id}. Cancelling proxy timer.")
            self.absence_timers[timer_key].cancel()
            del self.absence_timers[timer_key]

    def get_proxy_response(self, room_id, question, user_context):
        """Uses Gemini to respond as the absent user."""
        # Wrap user_context as a chunk for generate_answer
        context_chunks = [{'content': user_context}]
        return generate_answer(context_chunks, question)

ai_service = AIService()
