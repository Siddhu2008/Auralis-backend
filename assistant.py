from flask import Blueprint, request, jsonify
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.ai_service_unified import ai_service
from utils.jwt_handler import decode_token
from models.user import find_user_by_id
from models.reminder import create_reminder, get_user_reminders
from models.action_log import log_action, get_action_history

_DEFAULT_AI_MODEL = 'gemini-1.5-flash'
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
from services.ml.intent_classifier import intent_engine
from models.productivity_metrics import get_or_create_daily_metrics
from models.user_behavior import log_user_behavior

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

# Using unified ai_service instead of local get_client

@assistant_bp.route('/chat', methods=['POST'])
def assistant_chat():
    print(f"[ASSISTANT] New request received at {datetime.now()}")
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception as e:  # BUG-008 fix
        return jsonify({"error": "Invalid token"}), 401

    data = request.json
    user_message = data.get('message', '')
    
    log_user_behavior(user_id, 'assistant_chat', feature_used='chat')
    
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

    intent_guess = intent_engine.predict_intent(user_message)
    print(f"[ASSISTANT ML] Detected local intent: {intent_guess}")

    token_limit_map = {"short": 256, "medium": 640, "detailed": 1024}
    max_output_tokens = token_limit_map.get(user_settings.assistant_response_length, 640)

    prompt = f"""
    You are the 'Auralis Executive Assistant', a premium AI manager for high-stakes professionals.
    User-configured tone: {user_settings.assistant_tone}.
    Preferred language: {user_settings.language}.
    Response style length: {user_settings.assistant_response_length}.
    Auto follow-up suggestions enabled: {user_settings.auto_followups_enabled}.
    Your tone must strictly align with the configured tone while remaining helpful.
    
    [SYSTEM ML CLASSIFIER CLUE]: The AI classifier has detected the intent as: '{intent_guess}'. 
    Use this to strictly format your action response if it is an actionable intent.
    
    SYSTEM CONTEXT:
    {json.dumps(context, indent=2)}
    
    NATURE OF YOUR RESPONSE:
    - If the user wants to schedule a meeting, extract: title, date, time, and participants (if any).
    - If the user wants to modify an existing meeting (check upcoming_schedules), extract: schedule_id, and new fields.
    - If the user wants to cancel a meeting, extract: schedule_id.
    - If the user wants to draft/send an email, extract: recipient, subject, and body.
    - If information is missing, ask for it.
    - Use 'user_preferences' to suggest optimal times or frequent contacts.
    - Respect working hours from settings when proposing meeting times.
    
    OUTPUT FORMAT:
    Return JSON:
    {{
      "response": "Agent response string",
      "action": "schedule" | "modify" | "cancel" | "email" | "task" | "sync" | "set_pref" | null,
      "action_data": {{
         "title": "...", "start_time": "ISO_TIMESTAMP", "participants": [], "recipient": "...", "subject": "...", "body": "...", "schedule_id": "..."
      }}
    }}
    
    User Message: {user_message}
    """

    default_response = "I analyzed your context and I am ready to help with scheduling, communication, and action tracking."
    try:
        print(f"[ASSISTANT] Calling AI with prompt: {user_message[:50]}...")
        res_data = ai_structured_chat(
            prompt,
            default_response=default_response,
        )
        print(f"[ASSISTANT] AI call returned: {bool(res_data.get('response'))}")

        # AI-TO-ACTION AUTOMATION
        action = res_data.get("action")
        ad = res_data.get("action_data") or {}

        if action == "schedule":
            try:
                # Automate scheduling
                title = ad.get("title") or "Meeting with Assistant"
                start_time = ad.get("start_time")
                if start_time:
                    create_schedule(
                        user_id=user_id,
                        title=title,
                        start_time=start_time,
                        participants=ad.get("participants", []),
                        duration_minutes=ad.get("duration_minutes", 30)
                    )
                    log_action(user_id, "schedule", f"Scheduled: {title} at {start_time}")
                    res_data["response"] += f"\n\n[System Notification: I've successfully added '{title}' to your schedule for {start_time}.]"
            except Exception as se:
                print(f"Auto-Schedule Error: {se}")

        elif action == "email":
            try:
                recipient = ad.get("recipient")
                subject = ad.get("subject") or "Message from Auralis"
                body = ad.get("body")
                if recipient and body:
                    # BUG-007 FIX: Check approval settings BEFORE auto-sending email
                    settings_check = get_or_create_user_settings(user_id)
                    approved = False  # Auto-chat emails are never pre-approved
                    if settings_check.require_email_approval and not _can_auto_send_email(settings_check, recipient, approved):
                        # Don't auto-send — let the UI show the ActionCard confirmation
                        res_data["response"] += "\n\n[Note: Email draft ready. Please confirm before sending.]"
                    else:
                        success = send_email_custom(recipient, subject, body)
                        if success:
                            create_email_entry(
                                user_id=user_id,
                                subject=subject,
                                body=body,
                                summary=body[:80],
                                recipient=recipient,
                                direction='outgoing',
                                category='normal',
                                approved=True
                            )
                            log_action(user_id, "email", f"Sent email to {recipient}")
                            res_data["response"] += f"\n\n[System Notification: Your email to {recipient} has been dispatched successfully.]"
            except Exception as ee:  # BUG-008 fix
                print(f"Auto-Email Error: {ee}")

        elif action == "cancel":
             sid = ad.get("schedule_id")
             if sid:
                 delete_schedule(sid, user_id)
                 res_data["response"] += f"\n\n[System Notification: Meeting {sid} has been cancelled.]"

        # If AI path degraded to generic fallback, use a deterministic contextual answer.
        if (
            (res_data.get("response") or "").strip() == default_response
            and not res_data.get("action")
        ):
            res_data = contextual_fallback_response(user_message, context)
            if not ai_service.client:
                res_data["response"] = "I'm currently in low-power mode (API key missing). I can still help with some basic context, but my full intelligence is unavailable."

        add_memory(user_id, f"USER: {user_message}")
        add_memory(user_id, f"ASSISTANT: {res_data.get('response', '')}")
        return jsonify(normalize_chat_payload(res_data, "I am ready to assist.")), 200
    except Exception as e:  # BUG-008 fix
        print(f"Assistant AI Error: {e}")
        return jsonify(normalize_chat_payload({
            "response": "The Auralis core is currently experiencing a temporary synchronization delay. I'm automatically attempting to re-establish connection. Please try your request again in a moment.",
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
    except Exception as e:  # BUG-008 fix
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
    except Exception as e:  # BUG-008 fix
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
        summary_text = f"You have {len(schedules)} meetings and {len(reminders)} tasks."
        metrics = get_or_create_daily_metrics(user_id)
        
        briefing_context = {
            "schedules": schedules,
            "reminders": reminders,
            "recent_emails": emails,
            "today_productivity": metrics.to_dict() if metrics else {}
        }
        prompt = f"""
        You are the 'Auralis Executive Assistant'.
        Provide a concise, ultra-professional 1-2 sentence briefing based on this context:
        {json.dumps(briefing_context, indent=2)}
        
        Tone: Executive, encouraging, focused.
        """
        try:
            res = ai_service.generate_content(prompt, model=_DEFAULT_AI_MODEL)  # BUG-020 fix
            if res:
                summary_text = res
        except Exception:  # BUG-008 fix
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
    except Exception as e:  # BUG-008 fix
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
@assistant_bp.route('/clear-interactions', methods=['POST'])
def clear_interactions():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        from database import db
        from models.ai_memory import AIMemory
        payload = decode_token(token)
        user_id = payload['user_id']
        AIMemory.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        return jsonify({"message": "Interaction history redacted."}), 200
    except Exception as e:
        print(f"[DEBUG] Clear interactions error: {e}")
        return jsonify({"error": str(e)}), 500

@assistant_bp.route('/reset-schema', methods=['POST'])
def reset_schema():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        from database import db
        from models.ai_memory import AIMemory
        payload = decode_token(token)
        user_id = payload['user_id']
        AIMemory.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        return jsonify({"message": "Neural schema reset complete."}), 200
    except Exception as e:
        print(f"[DEBUG] Reset schema error: {e}")
        return jsonify({"error": str(e)}), 500
