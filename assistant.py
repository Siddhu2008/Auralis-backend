from flask import Blueprint, request, jsonify
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from google.genai import Client
from utils.jwt_handler import decode_token
from models.user import find_user_by_id
from models.reminder import create_reminder, get_user_reminders
from models.action_log import log_action, get_action_history
from models.user_preference import get_preferences, set_preference
from models.user_settings import get_or_create_user_settings
from models.schedule import create_schedule, update_schedule, delete_schedule, get_user_schedules
from models.meeting import get_user_meetings
from models.ai_memory import add_memory, search_memory
from models.task import create_task, get_user_tasks, get_task_metrics
from models.email import create_email_entry, get_user_emails
from utils.email_handler import send_email_otp, send_email_custom
from utils.email_reader import fetch_recent_emails
from utils.summarizer import summarize_text
from utils.assistant_intelligence import (
    ai_structured_chat,
    categorize_email,
    contextual_fallback_response,
    extract_action_items,
    normalize_chat_payload,
    suggest_proactive_items,
)

assistant_bp = Blueprint('assistant', __name__)


def _normalize_email(value):
    return (value or "").strip().lower()


def _can_auto_send_email(settings, recipient, approved):
    autonomy = (settings.assistant_autonomy_level or "assisted").lower()
    recipient_norm = _normalize_email(recipient)
    trusted = {
        _normalize_email(item)
        for item in (settings.trusted_contacts or [])
        if isinstance(item, str)
    }

    if approved:
        return True
    if autonomy == "full" and recipient_norm and recipient_norm in trusted:
        return True
    return False

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
    memory_hits = search_memory(user_id, user_message, limit=5)

    context = {
        "recent_emails": recent_emails,
        "action_history": action_history,
        "user_preferences": user_prefs,
        "upcoming_schedules": upcoming_schedules,
        "recent_meeting_summaries": [{"title": m['title'], "summary": m['summary']} for m in recent_meetings],
        "memory_hits": memory_hits,
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

    default_response = "I analyzed your context and I am ready to help with scheduling, communication, and action tracking."
    try:
        res_data = ai_structured_chat(
            prompt,
            default_response=default_response,
        )
        # If AI path degraded to generic fallback, use a deterministic contextual answer.
        if (
            (res_data.get("response") or "").strip() == default_response
            and not res_data.get("action")
        ):
            res_data = contextual_fallback_response(user_message, context)

        add_memory(user_id, f"USER: {user_message}")
        add_memory(user_id, f"ASSISTANT: {res_data.get('response', '')}")
        return jsonify(normalize_chat_payload(res_data, "I am ready to assist.")), 200
    except Exception as e:
        print(f"Assistant AI Error: {e}")
        return jsonify(normalize_chat_payload({
            "response": "I am experiencing a temporary neural desync. Please standby while I re-establish connection.",
            "action": None,
            "action_data": {},
            "confidence": 0.3,
        })), 200

@assistant_bp.route('/summarize', methods=['POST'])
def assistant_summarize():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except:
        return jsonify({"error": "Invalid token"}), 401

    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        summary = summarize_text(text)
        add_memory(user_id, f"SUMMARY: {summary}")
        return jsonify({"summary": summary}), 200
    except Exception as e:
        return jsonify({"error": "Failed to summarize text"}), 500

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
        date_part = action_data.get('date')
        time_part = action_data.get('time')
        settings = get_or_create_user_settings(user_id)
        tz_name = settings.timezone or "UTC"
        try:
            local_dt = datetime.fromisoformat(f"{date_part}T{time_part}:00")
            local_tz = ZoneInfo(tz_name)
            start_time = local_dt.replace(tzinfo=local_tz).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
        except Exception:
            return jsonify({"error": "Schedule action requires valid date and time"}), 400
        participants = action_data.get('participants', [])
        try:
            schedule = create_schedule(user_id, title, start_time, participants, request_timezone=tz_name)
            log_action(user_id, 'schedule', action_data)
            return jsonify({"status": "executed", "message": f"Session '{title}' successfully initialized."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    elif action == 'modify':
        if not bool(action_data.get("confirmed", False)):
            return jsonify({"error": "Please confirm meeting edit before applying changes."}), 400
        sch_id = action_data.get('schedule_id')
        try:
            start_time = None
            if action_data.get('date') and action_data.get('time'):
                settings = get_or_create_user_settings(user_id)
                tz_name = settings.timezone or "UTC"
                local_dt = datetime.fromisoformat(f"{action_data.get('date')}T{action_data.get('time')}:00")
                local_tz = ZoneInfo(tz_name)
                start_time = local_dt.replace(tzinfo=local_tz).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
            schedule = update_schedule(sch_id, user_id, 
                                     title=action_data.get('title'),
                                     start_time=start_time,
                                     participants=action_data.get('participants'))
            log_action(user_id, 'modify', action_data)
            return jsonify({"status": "executed", "message": "Neural parameters adjusted."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif action == 'cancel':
        if not bool(action_data.get("confirmed", False)):
            return jsonify({"error": "Please confirm meeting cancellation before proceeding."}), 400
        sch_id = action_data.get('schedule_id')
        if delete_schedule(sch_id, user_id):
            log_action(user_id, 'cancel', {"schedule_id": sch_id})
            return jsonify({"status": "executed", "message": "Session terminated."}), 200
        return jsonify({"error": "Protocol not found"}), 404

    elif action == 'email':
        settings = get_or_create_user_settings(user_id)
        approved = bool(action_data.get("approved", False))
        to = action_data.get('to')
        if settings.require_email_approval and not _can_auto_send_email(settings, to, approved):
            return jsonify({"error": "Email send blocked until explicit approval is provided."}), 400

        subject = action_data.get('subject', 'Message from Auralis Assistant')
        body = action_data.get('body')
        try:
            send_email_custom(to, subject, body)
            category = categorize_email(subject, body)
            create_email_entry(
                user_id=user_id,
                subject=subject,
                body=body,
                summary=summarize_text(body) if len(body) > 60 else body,
                recipient=to,
                direction="outgoing",
                category=category,
                approved=approved,
            )
            for item in extract_action_items(body):
                create_task(user_id, item["title"], source_type="email")
            log_action(user_id, 'email', action_data)
            return jsonify({"status": "executed", "message": "Transmission dispatched."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif action == 'task':
        title = action_data.get('title')
        due = action_data.get('due', 'Today')
        try:
            reminder = create_reminder(user_id, title, due)
            create_task(user_id, title, source_type="assistant")
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


@assistant_bp.route('/query-memory', methods=['POST'])
def query_memory():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except:
        return jsonify({"error": "Invalid token"}), 401

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    hits = search_memory(user_id, query, limit=10)
    return jsonify({"results": hits}), 200


@assistant_bp.route('/proactive-check', methods=['GET'])
def proactive_check():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except:
        return jsonify({"error": "Invalid token"}), 401

    schedules = get_user_schedules(user_id)
    tasks = get_user_tasks(user_id, include_completed=False, limit=100)
    emails = get_user_emails(user_id, limit=50)
    suggestions = suggest_proactive_items(schedules, tasks, emails)
    return jsonify({"suggestions": suggestions}), 200

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
        tasks = get_user_tasks(user_id, include_completed=False, limit=50)
        
        return jsonify({
            "schedules": schedules,
            "reminders": reminders,
            "tasks": tasks,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
