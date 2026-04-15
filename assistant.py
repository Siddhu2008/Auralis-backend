from flask import Blueprint, request, jsonify
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.ai_service_unified import ai_service
from utils.jwt_handler import decode_token
from models.user import find_user_by_id
# No reminder imports
from models.action_log import log_action, get_action_history

_DEFAULT_AI_MODEL = 'gemini-1.5-flash'
from models.user_preference import get_preferences, set_preference
from models.user_settings import get_or_create_user_settings
from models.schedule import create_schedule, update_schedule, delete_schedule, get_user_schedules
from models.meeting import get_user_meetings
from models.ai_memory import add_memory, search_memory, get_recent_memory
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
from utils.google_calendar_handler import sync_event_to_google
from services.ml.habit_cluster import habit_engine

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

    try:
        data = request.json
        user_message = data.get('message', '')
        current_page = data.get('current_page', 'dashboard')
        
        log_user_behavior(user_id, 'assistant_chat', feature_used='chat')
        
        # Fetch Memory & Context in Parallel
        import concurrent.futures
        
        def safe_fetch_emails():
            try:
                is_sync_request = any(kw in user_message.lower() for kw in ["email", "inbox", "sync", "schedule for today", "fetch", "check my mail"])
                if is_sync_request:
                    return fetch_recent_emails(limit=5)
            except Exception as e:
                print(f"[ASSISTANT] Email fetch error: {e}")
            return []

        def safe_search_memory():
            try:
                return search_memory(user_id, user_message, limit=5)
            except Exception as e:
                print(f"[ASSISTANT] Memory search error: {e}")
            return []

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
                future_emails = executor.submit(safe_fetch_emails)
                future_schedules = executor.submit(get_user_schedules, user_id)
                future_meetings = executor.submit(get_user_meetings, user_id)
                future_memory = executor.submit(safe_search_memory)
                future_prefs = executor.submit(get_preferences, user_id)
                future_tasks = executor.submit(get_user_tasks, user_id, False, 20)
                future_metrics = executor.submit(get_or_create_daily_metrics, user_id)
                
                recent_emails = future_emails.result() or []
                upcoming_schedules = future_schedules.result() or []
                recent_meetings = (future_meetings.result() or [])[:5]
                memory_hits = future_memory.result() or []
                user_prefs = future_prefs.result() or {}
                pending_tasks = future_tasks.result() or []
                
                daily_metrics_obj = future_metrics.result()
                daily_metrics = daily_metrics_obj.to_dict() if daily_metrics_obj else {}
        except Exception as e:
            print(f"[ASSISTANT] Parallel fetch error: {e}")
            recent_emails, upcoming_schedules, recent_meetings, memory_hits, user_prefs, pending_tasks, daily_metrics = [], [], [], [], {}, [], {}

        user_settings = get_or_create_user_settings(user_id)
        action_history = get_action_history(user_id, limit=10)

        context = {
            "recent_emails": recent_emails,
            "action_history": action_history,
            "user_preferences": user_prefs,
            "upcoming_schedules": [s.to_dict() if hasattr(s, 'to_dict') else s for s in upcoming_schedules],
            "recent_meeting_summaries": [{"title": m.get('title') if isinstance(m, dict) else getattr(m, 'title', 'Meeting'), "summary": m.get('summary') if isinstance(m, dict) else getattr(m, 'summary', '')} for m in recent_meetings],
            "pending_tasks": [t.to_dict() if hasattr(t, 'to_dict') else t for t in pending_tasks],
            "today_productivity": daily_metrics,
            "memory_hits": memory_hits,
            "current_time": datetime.utcnow().isoformat(),
            "current_page": current_page,
            "settings": user_settings.to_dict(),
        }

        default_response = "I analyzed your context and I am ready to help with scheduling, communication, and action tracking."
        try:
            # Move Intent Detection & Prompt building inside try block to avoid 500 errors
            intent_guess = intent_engine.predict_intent(user_message)
            print(f"[ASSISTANT ML] Detected local intent: {intent_guess}")

            # Stringify non-serializable objects in context safely
            for em in recent_emails:
                if 'parsed_date' in em and hasattr(em['parsed_date'], 'isoformat'):
                    em['parsed_date'] = em['parsed_date'].isoformat()

            token_limit_map = {"short": 256, "medium": 640, "detailed": 1024}
            max_output_tokens = token_limit_map.get(user_settings.assistant_response_length, 640)

            prompt = f"""
You are **Auralis Executive Assistant** — a Digital Twin-powered AI personal manager.
Your role is to automate and manage the user's professional life including meetings,
emails, tasks, reminders, and proactive intelligence. You are NOT a generic chatbot;
you are a personalized, context-aware agent for a busy professional.

=== ABOUT AURALIS (your capabilities) ===
1. Meeting Management: Schedule, reschedule, cancel, and detect conflicts. Support AI proxy mode where you attend meetings on the user's behalf.
2. Email Management: Sync inbox, summarize emails, draft professional replies, and send with user approval.
3. Task Management: Create, update, prioritize, and complete tasks. Suggest AI-driven tasks from context.
4. Daily Briefing: Summarize the user's day — meetings, tasks, and priorities.
6. Digital Twin: Track user behavior, learn their patterns (peak hours, frequent contacts, habits), and predict needs.
7. Smart Context: Use upcoming_schedules, pending_tasks, today_productivity, recent_emails, and memory_hits to make every response hyper-personalized. Always use today_productivity score and pending_tasks when asked about your agenda or productivity explicitly.
8. Conflict Detection: Detect overlapping meetings and suggest free slots based on working hours.

=== USER CONFIGURATION ===
- Tone: {user_settings.assistant_tone}
- Language: {user_settings.language}
- Response length: {user_settings.assistant_response_length}
- Auto follow-ups: {user_settings.auto_followups_enabled}
- Working hours: Use settings to suggest meeting times within business hours only.

=== ML INTENT CLASSIFIER HINT ===
The ML classifier detected intent: '{intent_guess}'.
Use this to anchor your action. If the intent is actionable (schedule, email, task, proxy_meeting, show_insights), execute it with proper action_data.

=== LIVE USER CONTEXT ===
- Current Page: {current_page}
{json.dumps(context, indent=2)}

=== HOW TO RESPOND ===
- schedule_meeting → action="schedule", extract: title, start_time (ISO), participants, duration_minutes
- cancel_meeting → action="cancel", extract: schedule_id from upcoming_schedules
- reschedule_meeting → action="modify", extract: schedule_id, new start_time
- draft_email → action="email" with send=false, extract: recipient, subject, body
- send_email → action="email" with send=true, extract: recipient, subject, body
- create_task → action="task", extract: title, priority, due_at, description
- show_schedule → respond with a natural language summary from upcoming_schedules
- daily_briefing → summarize meetings, tasks, emails and suggest today's focus
- sync_email → action="sync", respond with inbox summary from recent_emails context
- show_insights → summarize user habits and behavioral patterns as the Digital Twin
- proxy_meeting → action="proxy", note which meeting the user wants to skip
- general_query → action="null", answer naturally and conversationally using live user context (e.g. today_productivity, pending_tasks) or your general AI knowledge if unrelated.
- complex_query → answer using your full knowledge and provided context

IMPORTANT RULES:
- If information is missing (e.g., no time given for a meeting), ask ONE focused question.
- Always check upcoming_schedules for conflicts before suggesting a time.
- Never auto-send emails unless settings allow it — always note draft status.
- Analyze 'pending_tasks' and 'today_productivity' context carefully when asked about agenda, productivity or tasks today.
- Address general topics seamlessly with action="null", instead of needlessly forcing an action.
- Answer questions about Auralis (e.g., "what can you do?") using the capability list above.
- Keep replies aligned with the configured tone and response length.

=== OUTPUT FORMAT (strict JSON) ===
{{
  "response": "Natural language reply to user",
  "action": "schedule|modify|cancel|email|task|sync|proxy|set_pref|null",
  "action_data": {{
    "title": "...", "start_time": "ISO_TIMESTAMP", "participants": [],
    "duration_minutes": 30, "recipient": "...", "subject": "...", "body": "...",
    "schedule_id": "...", "priority": "normal|high|low", "due_at": "ISO_TIMESTAMP",
    "description": "...", "send": false
  }},
  "confidence": 0.0
}}

User Message: {user_message}
"""

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
                        sch = create_schedule(
                            user_id=user_id,
                            title=title,
                            start_time=start_time,
                            participants=ad.get("participants", []),
                            duration_minutes=ad.get("duration_minutes", 30)
                        )
                        # Sync to Google Calendar
                        sync_event_to_google(user_id, sch)
                        log_action(user_id, "schedule", f"Scheduled: {title} at {start_time}")
                        res_data["response"] += f"\n\n[System Notification: I've successfully added '{{title}}' to your schedule and synced it with your Google Calendar.]"
                except Exception as se:
                    print(f"Auto-Schedule Error: {{se}}")

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
                                log_action(user_id, "email", f"Sent email to {{recipient}}")
                                res_data["response"] += f"\n\n[System Notification: Your email to {{recipient}} has been dispatched successfully.]"
                except Exception as ee:  # BUG-008 fix
                    print(f"Auto-Email Error: {{ee}}")

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
        except Exception as e:
            import traceback
            error_data = f"\n[ASSISTANT ERROR] {e}\n{traceback.format_exc()}\n"
            print(error_data)
            with open('error.log', 'a', encoding='utf-8') as f:
                f.write(error_data)
            return jsonify(normalize_chat_payload({
                "response": "I'm having a brief synchronization delay with my brain modules, but I'm still here to help! What's on your mind?",
                "action": None,
                "action_data": {},
                "confidence": 0.3,
            })), 200
    except Exception as e:
        import traceback
        error_data = f"\n[ASSISTANT FATAL ERROR] {e}\n{traceback.format_exc()}\n"
        print(error_data)
        with open('error.log', 'a', encoding='utf-8') as f:
            f.write(error_data)
        return jsonify(normalize_chat_payload({
            "response": "I'm having a brief synchronization delay with my brain modules, but I'm still here to help! What's on your mind?",
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
            # Sync to Google Calendar
            sync_event_to_google(user_id, schedule)
            log_action(user_id, 'schedule', action_data)
            return jsonify({"status": "executed", "message": f"Session '{title}' successfully initialized and synced."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    elif action == 'reschedule' or action == 'modify':
        sch_id = action_data.get('schedule_id')
        if not sch_id:
            return jsonify({"error": "Schedule ID is required for rescheduling"}), 400
            
        title = action_data.get('title')
        date_part = action_data.get('date')
        time_part = action_data.get('time')
        
        start_time = None
        if date_part and time_part:
            settings = get_or_create_user_settings(user_id)
            tz_name = settings.timezone or "UTC"
            try:
                # Handle YYYY-MM-DD or other formats
                local_dt = datetime.fromisoformat(f"{date_part}T{time_part}:00")
                local_tz = ZoneInfo(tz_name)
                start_time = local_dt.replace(tzinfo=local_tz).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
            except Exception:
                return jsonify({"error": "Invalid date or time format"}), 400
        
        try:
            schedule = update_schedule(sch_id, user_id, 
                                     title=title,
                                     start_time=start_time,
                                     participants=action_data.get('participants'))
            # Sync to Google Calendar
            if schedule:
                sync_event_to_google(user_id, schedule)
            log_action(user_id, 'reschedule', action_data)
            return jsonify({"status": "executed", "message": "Neural parameters adjusted. Meeting rescheduled and synced."}), 200
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
        to = action_data.get('recipient') or action_data.get('to')
        
        import re
        if not to or not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", to):
            return jsonify({"error": "A valid recipient email address is required to proceed."}), 400
            
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
        try:
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


@assistant_bp.route('/memories', methods=['GET'])
def get_memories():
    """Return recent conversational memories for the Memory tab."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    try:
        memories = get_recent_memory(user_id, limit=40)
        formatted = []
        for m in memories:
            content = m.get('content', '')
            # Parse role prefix
            if content.startswith('USER: '):
                role = 'user'
                text = content[6:].strip()
            elif content.startswith('AI: '):
                role = 'assistant'
                text = content[4:].strip()
            else:
                role = 'system'
                text = content.strip()

            if text:
                formatted.append({
                    "id": m['id'],
                    "role": role,
                    "content": text,
                    "created_at": m.get('created_at', '')
                })

        return jsonify({"memories": formatted}), 200
    except Exception as e:
        import traceback
        print(f"[ERROR] get_memories: {e}\n{traceback.format_exc()}")
        return jsonify({"memories": []}), 200


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
        emails = fetch_recent_emails(limit=5)
        # Power the briefing with AI
        summary_text = f"You have {len(schedules)} meetings."
        metrics = get_or_create_daily_metrics(user_id)
        
        recommendations = habit_engine.get_autonomous_recommendations(user_id)
        
        briefing_context = {
            "schedules": schedules,
            "recent_emails": emails,
            "today_productivity": metrics.to_dict() if metrics else {},
            "behavior_recommendations": recommendations
        }
        prompt = f"""
        You are the 'Auralis Executive Assistant'. Generate a 'Smart Daily Plan'.
        Context:
        {json.dumps(briefing_context, indent=2)}
        
        Format your response EXACTLY like this example (using bullet points and emojis):
        Good morning 👋
        You have X meetings today.
        1 critical deadline detected.
        
        Suggested: [High priority recommendation based on context]
        
        Keep it professional and concise.
        """
        try:
            res = ai_service.generate_content(prompt, model=_DEFAULT_AI_MODEL)
            if res:
                summary_text = res
        except Exception:
            pass

        return jsonify({
            "upcoming_meetings": schedules,
            "urgent_tasks": [],
            "recent_communications": len(emails),
            "summary_text": summary_text,
            "recommendations": recommendations,
            "briefing_type": "smart_daily_plan"
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
        tasks = get_user_tasks(user_id, include_completed=False, limit=50)
        
        return jsonify({
            "schedules": schedules,
            "tasks": tasks,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@assistant_bp.route('/history', methods=['GET', 'OPTIONS'])
def get_history():
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200
    
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        # 1. Fetch action logs
        try:
            history = get_action_history(user_id, limit=15)
        except Exception as e:
            print(f"[DEBUG] get_action_history failed: {e}")
            history = []
            
        # 2. Fetch conversational memory
        try:
            memories = get_recent_memory(user_id, limit=30)
        except Exception as e:
            print(f"[DEBUG] get_recent_memory failed: {e}")
            memories = []
        
        formatted = []
        for h in history:
            title = h.get('action_data', {}).get('title', h.get('action_type', 'System Action').capitalize())
            formatted.append({
                "id": f"act_{h['id']}",
                "title": title,
                "type": h['action_type'],
                "date": h.get('timestamp') or datetime.utcnow().isoformat()
            })
            
        for m in memories:
            content = m.get('content', '')
            if content.startswith("USER: "):
                title = content[6:].strip()
                if not title: continue # Skip empty queries
                if len(title) > 40:
                    title = title[:37] + "..."
                formatted.append({
                    "id": f"mem_{m['id']}",
                    "title": f"Chat: {title}",
                    "type": "chat",
                    "date": m.get('created_at') or datetime.utcnow().isoformat()
                })
                
        # Sort chronologically (descending) by date string
        # Use a lambda that handles Nones just in case
        formatted.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        # Limit result set
        formatted = formatted[:15]

        return jsonify({"history": formatted}), 200
    except Exception as e:
        import traceback
        print(f"[ERROR] get_history fatal: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal synchronization error in history modules."}), 500

@assistant_bp.route('/history/<item_id>', methods=['GET', 'DELETE', 'PATCH', 'OPTIONS'])
def manage_history_item(item_id):
    """Manage a specific history item (rename or delete)."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        from database import db
        from models.ai_memory import AIMemory
        from models.action_log import ActionLog

        # Extract ID and type
        try:
            if item_id.startswith('mem_'):
                real_id = int(item_id[4:])
                item_type = 'memory'
            elif item_id.startswith('act_'):
                real_id = int(item_id[4:])
                item_type = 'action'
            else:
                return jsonify({"error": "Invalid interaction ID protocol"}), 400
        except ValueError:
            return jsonify({"error": "Malformed interaction ID"}), 400

        if request.method == 'GET':
            if item_type == 'memory':
                item = AIMemory.query.filter_by(id=real_id, user_id=user_id).first()
                if not item: return jsonify({"error": "Memory not found"}), 404
                return jsonify({
                    "id": item_id,
                    "title": f"Chat: {item.content[6:46].strip()}..." if len(item.content) > 46 else f"Chat: {item.content[6:].strip()}",
                    "content": item.content,
                    "type": "chat",
                    "date": item.created_at.isoformat() if item.created_at else None
                }), 200
            else: # item_type == 'action'
                item = ActionLog.query.filter_by(id=real_id, user_id=user_id).first()
                if not item: return jsonify({"error": "Action not found"}), 404
                return jsonify({
                    "id": item_id,
                    "title": item.action_data.get('title', item.action_type.capitalize()),
                    "type": item.action_type,
                    "details": item.action_data, # Use action_data for full details
                    "date": item.timestamp.isoformat() if item.timestamp else None
                }), 200
        
        elif request.method == 'DELETE':
            if item_id.startswith('mem_'):
                mid = int(item_id.split('_')[1])
                AIMemory.query.filter_by(id=mid, user_id=user_id).delete()
            elif item_id.startswith('act_'):
                from models.action_log import ActionLog
                aid = int(item_id.split('_')[1])
                ActionLog.query.filter_by(id=aid, user_id=user_id).delete()
            else:
                return jsonify({"error": "Invalid interaction ID protocol"}), 400
            db.session.commit()
            return jsonify({"status": "redacted", "message": "Neural traces cleared."}), 200
            
        elif request.method == 'PATCH':
            data = request.json
            new_title = data.get('title')
            if not new_title:
                return jsonify({"error": "Title is required"}), 400
                
            if item_id.startswith('mem_'):
                from models.ai_memory import AIMemory
                mid = int(item_id.split('_')[1])
                mem = AIMemory.query.filter_by(id=mid, user_id=user_id).first()
                if mem:
                    mem.content = f"USER: {new_title}"
                else: return jsonify({"error": "Not found"}), 404
            elif item_id.startswith('act_'):
                from models.action_log import ActionLog
                aid = int(item_id.split('_')[1])
                log = ActionLog.query.filter_by(id=aid, user_id=user_id).first()
                if log:
                    new_data = dict(log.action_data)
                    new_data['title'] = new_title
                    log.action_data = new_data
                else: return jsonify({"error": "Not found"}), 404
            else:
                return jsonify({"error": "Invalid interaction ID protocol"}), 400
            db.session.commit()
            return jsonify({"status": "updated", "message": "Neural schema adjusted."}), 200
            
    except Exception as e:
        import traceback
        print(f"[ERROR] manage_history_item: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@assistant_bp.route('/clear', methods=['POST'])
def clear_history():
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

@assistant_bp.route('/reset', methods=['POST'])
def reset_preferences():
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
