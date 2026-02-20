from flask import Blueprint, request, jsonify
import os
import json
from datetime import datetime
from google.genai import Client
from utils.jwt_handler import decode_token
from models.user import find_user_by_id
from models.reminder import create_reminder, get_user_reminders
from models.action_log import log_action, get_action_history
from models.user_preference import get_preferences, set_preference
from models.user_settings import get_or_create_user_settings
from models.schedule import create_schedule, update_schedule, delete_schedule, get_user_schedules
from models.meeting import get_user_meetings
from utils.email_handler import send_email_otp, send_email_custom
from utils.email_reader import fetch_recent_emails

assistant_bp = Blueprint('assistant', __name__)

def get_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    return Client(api_key=api_key)

@assistant_bp.route('/chat', methods=['POST'])
def assistant_chat():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except:
        return jsonify({"error": "Invalid token"}), 401

    data = request.json
    user_message = data.get('message', '')
    
    client = get_client()
    if not client:
        return jsonify({"error": "AI Service unavailable"}), 503

    # Fetch Memory & Context
    recent_emails = []
    is_sync_request = any(kw in user_message.lower() for kw in ["email", "inbox", "sync", "schedule for today", "fetch", "check my mail"])
    if is_sync_request:
        recent_emails = fetch_recent_emails(limit=5)

    action_history = get_action_history(user_id, limit=10)
    user_prefs = get_preferences(user_id)
    user_settings = get_or_create_user_settings(user_id)
    upcoming_schedules = get_user_schedules(user_id)
    recent_meetings = get_user_meetings(user_id)[:5] # Last 5 meeting summaries

    context = {
        "recent_emails": recent_emails,
        "action_history": action_history,
        "user_preferences": user_prefs,
        "upcoming_schedules": upcoming_schedules,
        "recent_meeting_summaries": [{"title": m['title'], "summary": m['summary']} for m in recent_meetings],
        "current_time": datetime.utcnow().isoformat(),
        "settings": user_settings.to_dict(),
    }

    token_limit_map = {"short": 256, "medium": 640, "detailed": 1024}
    max_output_tokens = token_limit_map.get(user_settings.assistant_response_length, 640)

    prompt = f"""
    You are the 'Auralis Executive Assistant', a premium AI manager for high-stakes professionals.
    User-configured tone: {user_settings.assistant_tone}.
    Preferred language: {user_settings.language}.
    Response style length: {user_settings.assistant_response_length}.
    Auto follow-up suggestions enabled: {user_settings.auto_followups_enabled}.
    Your tone must strictly align with the configured tone while remaining helpful.
    
    SYSTEM CONTEXT:
    {json.dumps(context, indent=2)}
    
    NATURE OF YOUR RESPONSE:
    - If the user wants to schedule a meeting, extract: title, date, time, and participants (if any).
    - If the user wants to modify an existing meeting (check upcoming_schedules), extract: schedule_id, and new fields.
    - If the user wants to cancel a meeting, extract: schedule_id.
    - If the user wants to draft an email, extract: recipient, subject, and tone/body.
    - If information is missing, ask for it.
    - Use 'user_preferences' to suggest optimal times or frequent contacts.
    - Use 'action_history' to avoid duplicating tasks.
    - Respect working hours from settings when proposing meeting times.
    - If auto follow-up is disabled, do not add unsolicited follow-up suggestions.
    
    OUTPUT FORMAT:
    Return JSON:
    {{
      "response": "Agent response string",
      "action": "schedule" | "modify" | "cancel" | "email" | "task" | "sync" | "set_pref" | null,
      "action_data": {{ ... }}
    }}
    
    User Message: {user_message}
    """

    try:
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'max_output_tokens': max_output_tokens,
            }
        )
        
        # Parse the JSON response from Gemini
        try:
            # Clean up potential markdown formatting if Gemini adds it
            clean_text = response.text.strip()
            if "```json" in clean_text:
                clean_text = clean_text.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_text:
                clean_text = clean_text.split("```")[1].split("```")[0].strip()
            
            res_data = json.loads(clean_text)
            return jsonify(res_data), 200
        except Exception as parse_err:
            print(f"AI JSON Parse Error: {parse_err} | Raw: {response.text}")
            return jsonify({
                "response": response.text if response.text else "I have processed your request, but the output protocol was non-standard. How else can I assist?",
                "action": None
            }), 200
        
    except Exception as e:
        print(f"Assistant AI Error: {e}")
        return jsonify({
            "response": "I am experiencing a temporary neural desync. Please standby while I re-establish connection.",
            "action": None
        }), 200

@assistant_bp.route('/execute', methods=['POST'])
def assistant_execute():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except:
        return jsonify({"error": "Invalid token"}), 401

    data = request.json
    action = data.get('action')
    action_data = data.get('data')

    if action == 'schedule':
        title = action_data.get('title', 'Meeting')
        start_time = f"{action_data.get('date')} {action_data.get('time')}"
        participants = action_data.get('participants', [])
        try:
            schedule = create_schedule(user_id, title, start_time, participants)
            log_action(user_id, 'schedule', action_data)
            return jsonify({"status": "executed", "message": f"Session '{title}' successfully initialized."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    elif action == 'modify':
        sch_id = action_data.get('schedule_id')
        try:
            schedule = update_schedule(sch_id, user_id, 
                                     title=action_data.get('title'),
                                     start_time=f"{action_data.get('date')} {action_data.get('time')}" if action_data.get('date') else None,
                                     participants=action_data.get('participants'))
            log_action(user_id, 'modify', action_data)
            return jsonify({"status": "executed", "message": "Neural parameters adjusted."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif action == 'cancel':
        sch_id = action_data.get('schedule_id')
        if delete_schedule(sch_id, user_id):
            log_action(user_id, 'cancel', {"schedule_id": sch_id})
            return jsonify({"status": "executed", "message": "Session terminated."}), 200
        return jsonify({"error": "Protocol not found"}), 404

    elif action == 'email':
        settings = get_or_create_user_settings(user_id)
        if settings.require_email_approval and not action_data.get("approved", False):
            return jsonify({"error": "Email send blocked until explicit approval is provided."}), 400

        to = action_data.get('to')
        subject = action_data.get('subject', 'Message from Auralis Assistant')
        body = action_data.get('body')
        try:
            send_email_custom(to, subject, body)
            log_action(user_id, 'email', action_data)
            return jsonify({"status": "executed", "message": "Transmission dispatched."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif action == 'task':
        title = action_data.get('title')
        due = action_data.get('due', 'Today')
        try:
            reminder = create_reminder(user_id, title, due)
            log_action(user_id, 'task', action_data)
            return jsonify({"status": "executed", "message": f"Task '{title}' logged."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif action == 'set_pref':
        key = action_data.get('key')
        val = action_data.get('value')
        set_preference(user_id, key, val)
        return jsonify({"status": "executed", "message": "Preference logged."}), 200

    return jsonify({"error": "Invalid action protocol"}), 400

@assistant_bp.route('/briefing', methods=['GET'])
def get_briefing():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except:
        return jsonify({"error": "Invalid token"}), 401

    try:
        settings = get_or_create_user_settings(user_id)
        if not settings.daily_briefing_enabled:
            return jsonify({
                "upcoming_meetings": [],
                "urgent_tasks": [],
                "recent_communications": 0,
                "summary_text": "Daily briefing is disabled in your settings."
            }), 200

        schedules = get_user_schedules(user_id)
        reminders = get_user_reminders(user_id)
        emails = fetch_recent_emails(limit=5)
        
        # Power the briefing with AI
        client = get_client()
        summary_text = f"Initial session established. You have {len(schedules)} meetings and {len(reminders)} tasks."
        
        if client:
            briefing_context = {
                "schedules": schedules,
                "reminders": reminders,
                "recent_emails": emails
            }
            prompt = f"""
            You are the 'Auralis Executive Assistant'.
            Provide a concise, ultra-professional 1-2 sentence briefing based on this context:
            {json.dumps(briefing_context, indent=2)}
            
            Tone: Executive, encouraging, focused.
            """
            try:
                response = client.models.generate_content(
                    model='gemini-flash-latest',
                    contents=prompt
                )
                summary_text = response.text.strip()
            except:
                pass

        return jsonify({
            "upcoming_meetings": schedules,
            "urgent_tasks": reminders,
            "recent_communications": len(emails),
            "summary_text": summary_text
        }), 200
    except Exception as e:
        print(f"Briefing Error: {e}")
        return jsonify({"error": str(e)}), 500

@assistant_bp.route('/agenda', methods=['GET'])
def get_agenda():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except:
        return jsonify({"error": "Invalid token"}), 401

    try:
        schedules = get_user_schedules(user_id)
        reminders = get_user_reminders(user_id)
        
        return jsonify({
            "schedules": schedules,
            "reminders": reminders
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
