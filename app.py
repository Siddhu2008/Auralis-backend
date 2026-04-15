import eventlet
eventlet.monkey_patch()

import os
os.environ['EVENTLET_NO_GREENDNS'] = 'yes' # Force system DNS to avoid Lookup timed out on Windows

from dotenv import load_dotenv
load_dotenv()

import dns.resolver
resolver = dns.resolver.Resolver()
resolver.nameservers = ['8.8.8.8']
dns.resolver.default_resolver = resolver

from datetime import datetime
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from datetime import datetime
from flask_cors import CORS
from auth import auth_bp
from assistant import assistant_bp
from profile_bp import profile_bp
from settings_bp import settings_bp
from timeline_bp import timeline_bp
from flask_socketio import SocketIO
from socket_events import register_socket_events
from meeting_system.realtime import register_meeting_socket_events
from meeting_system.routes import meeting_bp
from meeting_agent_bp import meeting_agent_bp
import meeting_system.models  # noqa: F401
from utils.jwt_handler import decode_token, generate_token
from utils.email_handler import send_email_otp, send_notification_email
from utils.vector_store import vector_store
from utils.ai_response import generate_answer
from models.meeting import create_meeting, get_user_meetings, get_meeting_by_id, delete_meeting, mark_meeting_completed
from models.schedule import create_schedule, get_user_schedules, delete_schedule
from models.notification import create_notification, get_user_notifications, mark_as_read
from models.user_settings import get_or_create_user_settings
from models.user import User
from models.user_settings import create_default_settings_for_user
from models.email import create_email_entry, get_user_emails, get_email_metrics
from models.ai_memory import add_memory
from models.task import create_task, get_task_metrics, get_user_tasks, update_task, delete_task
from models.productivity_metrics import get_or_create_daily_metrics, get_user_metrics
from utils.email_handler import send_email_custom
from utils.assistant_intelligence import categorize_email, extract_action_items
from utils.summarizer import summarize_text
from utils.ai_service_unified import ai_service
from models.user_behavior import UserBehaviorLog, get_user_behaviors
from services.google_sync_service import google_sync_service
from services.ml.habit_cluster import habit_engine
from utils import socket_instance # ADDED

from database import db, init_db, ensure_database_schema
from flask_migrate import Migrate
import models.email  # noqa: F401
import models.ai_memory  # noqa: F401
import models.task  # noqa: F401
import models.user_behavior  # noqa: F401
import models.productivity_metrics  # noqa: F401

# load_dotenv() - Moved to top

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
init_db(app)
ensure_database_schema(app)

cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in cors_origins_env.split(",")
    if origin.strip()
]
if not FRONTEND_ORIGINS:
    FRONTEND_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://auralis-frontend.vercel.app",
    ]
CORS(app, resources={r"/*": {
    "origins": FRONTEND_ORIGINS,
    "allow_headers": ["Authorization", "Content-Type", "X-Requested-With"],
    "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
}}, supports_credentials=True)
socketio = SocketIO(
    app, 
    cors_allowed_origins=FRONTEND_ORIGINS,
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25
)
socket_instance.socketio = socketio # ADDED

register_socket_events(socketio)
register_meeting_socket_events(socketio)

app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(assistant_bp, url_prefix='/api/assistant')
app.register_blueprint(profile_bp, url_prefix='/api/profile')
app.register_blueprint(settings_bp, url_prefix='/api/settings')
app.register_blueprint(timeline_bp, url_prefix='/api/timeline')
app.register_blueprint(meeting_bp, url_prefix='/api/meetings')
app.register_blueprint(meeting_agent_bp, url_prefix='/api/agent')



def reminder_worker():
    """Background worker to check for upcoming meetings and send reminders 5 minutes before."""
    print(" [Auralis] Reminder Worker Started.")
    while True:
        try:
            eventlet.sleep(60) # Run every minute
            with app.app_context():
                from meeting_system.models import MeetingV2
                from models.notification import create_notification
                from datetime import datetime, timedelta
                
                now = datetime.utcnow()
                # Check for meetings starting in 3-8 minutes (wider window)
                window_start = now + timedelta(minutes=3)
                window_end = now + timedelta(minutes=8)
                
                # Diagnostic: log current time and upcoming meetings regardless of window
                # print(f" [Auralis DEBUG] Reminder check at {now.isoformat()} (UTC)")
                
                upcoming = MeetingV2.query.filter(
                    MeetingV2.status == 'scheduled',
                    MeetingV2.reminder_sent == False,
                    MeetingV2.scheduled_start_at >= window_start,
                    MeetingV2.scheduled_start_at <= window_end
                ).all()
                
                for mtg in upcoming:
                    diff = mtg.scheduled_start_at - now
                    minutes_to_start = diff.total_seconds() / 60
                    print(f" [Auralis] MATCH: Meeting[{mtg.id}] '{mtg.title}' starts in {minutes_to_start:.1f}m. Sending reminder.")
                    msg = f"Your meeting '{mtg.title}' is starting in 5 minutes. Ready to join?"
                    create_notification(
                        user_id=mtg.user_id,
                        message=msg,
                        type='meeting',
                        title="Meeting Starting Soon"
                    )
                    mtg.reminder_sent = True
                
                if upcoming:
                    db.session.commit()
                    
        except Exception as e:
            print(f" [Auralis] Reminder Worker Error: {e}")
            eventlet.sleep(30)


def proactive_worker():
    """Background worker to push proactive insights to users."""
    print("[Auralis] Proactive Insight Worker Started.")
    while True:
        try:
            # Sleep for 2-3 minutes between checks to avoid spamming
            eventlet.sleep(150) 
            
            with app.app_context():
                # For demo/MVP, we find all active users with recent logs
                # In prod, this would be more targeted.
                users = User.query.all()
                for user in users:
                    # Sync Real-World Agency (Google)
                    if user.google_refresh_token:
                        print(f" [Auralis] Syncing Google Agency for User[{user.id}]")
                        cal_count = google_sync_service.sync_calendar(user.id)
                        mail_count = google_sync_service.sync_gmail(user.id)
                        if cal_count > 0 or mail_count > 0:
                            socketio.emit('agent_status', {
                                'message': f"Linked Intelligence: Synced {cal_count} calendar events and {mail_count} priority communications.",
                                'type': 'agency_sync'
                            }, room=f"user_{user.id}")

                    behaviors = get_user_behaviors(user.id, limit=10)
                    if not behaviors:
                        continue
                        
                    behavior_text = "\n".join([
                        f"- {b['action_type']} at hour {b['active_hour']} on day {b['day_of_week']}" 
                        for b in behaviors
                    ])
                    
                    insight = ai_service.get_proactive_insight(behavior_text)
                    if insight and not insight.startswith("ERR"):
                        print(f" [Auralis] Pushing insight to User[{user.id}]: {insight}")
                        socketio.emit('proactive_insight', {
                            'content': insight,
                            'timestamp': datetime.utcnow().isoformat()
                        }, room=f"user_{user.id}")

                    # Autonomous Habit Recommendations
                    habits = habit_engine.get_autonomous_recommendations(user.id)
                    for h in habits:
                        print(f" [Auralis] Pushing habit recommendation to User[{user.id}]: {h}")
                        socketio.emit('agent_status', {
                            'message': h,
                            'type': 'habit_recommendation'
                        }, room=f"user_{user.id}")
                        
        except Exception as e:
            print(f" [Auralis] Proactive Worker Error: {e}")
            eventlet.sleep(60)

_last_digest_sent = {}

def daily_digest_worker():
    """Background worker to send a daily digest of pending tasks and today's meetings."""
    print(" [Auralis] Daily Digest Worker Started.")
    while True:
        try:
            # Check periodically
            eventlet.sleep(120) 
            with app.app_context():
                from datetime import datetime
                now = datetime.utcnow()
                today_str = str(now.date())
                
                from models.user import User
                from models.user_settings import get_or_create_user_settings
                from models.task import get_user_tasks
                from meeting_system.models import MeetingV2
                from utils.email_handler import send_daily_digest_email
                
                users = User.query.all()
                for user in users:
                    if _last_digest_sent.get(user.id) == today_str:
                        continue
                        
                    settings = get_or_create_user_settings(user.id)
                    if not settings.email_notifications_enabled or not user.email:
                        continue
                        
                    tasks = get_user_tasks(user.id, include_completed=False, limit=50)
                    
                    start_of_day = datetime(now.year, now.month, now.day)
                    end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59)
                    
                    meetings = MeetingV2.query.filter(
                        MeetingV2.user_id == user.id,
                        MeetingV2.scheduled_start_at >= start_of_day,
                        MeetingV2.scheduled_start_at <= end_of_day,
                        MeetingV2.status.in_(['scheduled', 'live', 'active'])
                    ).order_by(MeetingV2.scheduled_start_at.asc()).all()
                    
                    if tasks or meetings:
                        print(f" [Auralis] Sending Daily Digest to User[{user.id}] ({user.email}).")
                        send_daily_digest_email(user.email, user.name, tasks, meetings)
                        
                    _last_digest_sent[user.id] = today_str
                    eventlet.sleep(2)
        except Exception as e:
            print(f" [Auralis] Daily Digest Worker Error: {e}")
            eventlet.sleep(60)

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


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    return jsonify({"error": error.description or "Request failed"}), error.code


@app.errorhandler(Exception)
def handle_unexpected_exception(error):
    import traceback
    error_msg = f"[UNHANDLED ERROR] {str(error)}\n{traceback.format_exc()}"
    print(error_msg)
    try:
        with open('error.log', 'a', encoding='utf-8') as f:
            f.write(f"\n{datetime.now().isoformat()} - {error_msg}\n")
    except:
        pass
    return jsonify({"error": "Internal server error"}), 500

@app.after_request
def add_security_headers(response):
    # Set COOP to allow Google OAuth popups to communicate back to the opener
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
    # Set COEP to allow cross-origin embeddings if needed, or stick to safe defaults
    response.headers['Cross-Origin-Embedder-Policy'] = 'unsafe-none'
    return response

@app.route('/api/ai/summarize', methods=['POST'])
def ai_summarize():
    auth_header = request.headers.get('Authorization')
    if not auth_header: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    text = data.get('text', '')
    if not text:
        return jsonify({"error": "No text provided"}), 400
        
    summary = summarize_text(text)
    return jsonify({"summary": summary})

@app.route('/api/ai/ask', methods=['POST'])
def ask_ai():
    auth_header = request.headers.get('Authorization')
    if not auth_header: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    question = data.get('question', '')
    if not question:
        return jsonify({"error": "No question provided"}), 400
    
    try:
        # 1. Search vector DB
        relevant_chunks = vector_store.search(question)
        
        # 2. Generate Answer
        answer = generate_answer(relevant_chunks, question)
        
        return jsonify({
            "answer": answer,
            "sources": relevant_chunks
        })
    except Exception as e:
        print(f"Chatbot Error: {e}")
        return jsonify({
            "answer": "The neural core is currently re-indexing. Please attempt your query again in a moment.",
            "sources": []
        }), 200

@app.route('/api/ai/transcribe', methods=['POST'])
def ai_transcribe():
    # Still keep this for backward compat or if needed, but we'll use summarize mostly
    return jsonify({"error": "Use summarize endpoint with Web Speech API"}), 400

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "AURALIS Backend",
        "version": "1.0.0"
    }), 200

@app.route('/api/dashboard', methods=['GET'])
def dashboard_overview():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        from meeting_system.models import MeetingV2
        from datetime import datetime as _dt
        from meeting_system.services import serialize_meeting_bundle
        
        now = _dt.utcnow()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # All v2 meetings for the user
        all_v2 = MeetingV2.query.filter_by(user_id=user_id).all()
        # Weekly (mocked as the last 20 for now to minimize complex date querying logic just like previous code)
        v2_weekly = sorted(all_v2, key=lambda x: x.created_at or now, reverse=True)[:20]
        completed_v2 = [m for m in all_v2 if m.status == "completed" or m.status == "ended"]
        def _get_v2_dur(m):
            if m.scheduled_end_at and m.scheduled_start_at:
                return (m.scheduled_end_at - m.scheduled_start_at).total_seconds() / 60.0
            return 30.0
            
        v2_weekly_hours = sum([_get_v2_dur(m) for m in v2_weekly]) / 60.0

        upcoming_v2 = (
            MeetingV2.query.filter(
                (MeetingV2.user_id == user_id) &
                (MeetingV2.status.in_(["scheduled", "live", "active"])) &
                ((MeetingV2.scheduled_start_at >= now) | (MeetingV2.status == "live"))
            )
            .order_by(MeetingV2.scheduled_start_at.asc())
            .all()
        )
        # Serialize and extract just the meeting object to match the schema
        schedules = [serialize_meeting_bundle(m)["meeting"] for m in upcoming_v2]
        
        from utils.email_reader import fetch_recent_emails
        emails = fetch_recent_emails(limit=5)
        
        return jsonify({
            "meetings_this_week": len(v2_weekly),
            "completed_meetings": len(completed_v2),
            "weekly_meeting_hours": round(v2_weekly_hours, 2),
            "task_metrics": get_task_metrics(user_id),
            "email_metrics": get_email_metrics(user_id),
            "pending_tasks": get_user_tasks(user_id, include_completed=False, limit=10),
            "ai_usage": {
                "assistant_queries_last_7d": 0,
                "summaries_generated": len([m for m in all_v2 if m.agent_report]),
            },
            "upcoming_schedules": schedules,
            "recent_emails": emails,
        }), 200
    except Exception as e:
        import traceback
        print(f"[DASHBOARD ERROR] {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Failed to build dashboard overview"}), 500

@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not name or not email or not password:
        return jsonify({"error": "name, email and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400

    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({"error": "Email already registered"}), 400

    try:
        user = User(email=email, name=name, provider='email')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        create_default_settings_for_user(user.id)
        jwt_token = generate_token(user_id=user.id, email=user.email, name=user.name)
        from models.user_behavior import log_user_behavior
        log_user_behavior(user.id, 'register', feature_used='auth')
        return jsonify({"token": jwt_token, "user": user.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to register user"}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.verify_password(password):
        return jsonify({"error": "Invalid credentials"}), 401
    jwt_token = generate_token(user_id=user.id, email=user.email, name=user.name, profile_image=user.profile_image, provider=user.provider)
    from models.user_behavior import log_user_behavior
    log_user_behavior(user.id, 'login', feature_used='auth')
    return jsonify({"token": jwt_token, "user": user.to_dict()}), 200

# Meeting API Endpoints
@app.route('/api/meetings', methods=['GET'])
def get_meetings():
    """Get all meetings for the authenticated user"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        meetings = get_user_meetings(user_id)
        return jsonify({"meetings": meetings}), 200
    except Exception as e:
        return jsonify({"error": "Invalid token"}), 401

@app.route('/api/meetings/past', methods=['GET'])
def get_past_meetings():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        meetings = get_user_meetings(user_id)
        past = []
        for meeting in meetings:
            status = meeting.get("status") or "completed"
            if status != "completed":
                continue
            participants_count = meeting.get("participants_count", 1)
            if isinstance(participants_count, int):
                participants = participants_count
            else:
                participants = 1
            past.append({
                "id": meeting.get("id"),
                "room_id": meeting.get("room_id"),
                "title": meeting.get("title"),
                "date": meeting.get("date"),
                "participants": participants,
                "duration": meeting.get("duration", "N/A"),
                "summary": meeting.get("summary"),
                "transcript": meeting.get("transcript"),
                "agent_report": meeting.get("agent_report"),
                "recording_link": meeting.get("recording_url"),
                "action_items": meeting.get("action_items", []),
            })
        return jsonify({"meetings": past}), 200
    except Exception as e:
        return jsonify({"error": "Invalid token"}), 401

@app.route('/api/meetings', methods=['POST'])
def create_new_meeting():
    """Create a new meeting"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        data = request.json
        meeting = create_meeting(
            user_id=user_id,
            room_id=data.get('room_id'),
            title=data.get('title'),
            transcript=data.get('transcript'),
            summary=data.get('summary'),
            duration=data.get('duration', 'N/A'),
            participants_count=data.get('participants_count', 1),
            recording_url=data.get('recording_url'),
            status=data.get('status', 'completed'),
            ended_at=datetime.utcnow() if data.get('status', 'completed') == 'completed' else None,
            action_items=data.get('action_items', []),
        )
        
        # Add to Vector Store (async/background ideally, but sync for now)
        if meeting and data.get('transcript'):
             # Using meeting['id']
             m_id = str(meeting.get('id'))
             text_content = f"Title: {meeting.get('title')}\nSummary: {meeting.get('summary')}\nTranscript: {meeting.get('transcript')}"
             vector_store.add_meeting(m_id, text_content, metadata={"title": meeting.get('title')})

        settings = get_or_create_user_settings(user_id)

        # Trigger Notifications
        if settings.notifications_enabled:
            create_notification(user_id, f"Meeting saved: {meeting.get('title')}", type='success')
        
        # Email Notification (optional, but requested by user)
        # Note: we need the email from payload
        user_email = payload.get('email')
        if user_email and settings.email_notifications_enabled:
            send_notification_email(user_email, meeting.get('title'), "now", type='meeting')

        return jsonify({"meeting": meeting}), 201
    except Exception as e:
        print(f"Create meeting error: {e}")
        return jsonify({"error": "Failed to create meeting"}), 500

@app.route('/api/meetings/<meeting_id>', methods=['GET'])
def get_meeting(meeting_id):
    """Get a specific meeting"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        meeting = get_meeting_by_id(meeting_id, user_id)
        if meeting:
            return jsonify({"meeting": meeting}), 200
        else:
            return jsonify({"error": "Meeting not found"}), 404
    except Exception as e:
        return jsonify({"error": "Invalid token"}), 401

@app.route('/api/meetings/<meeting_id>/download-pdf', methods=['GET'])
def download_meeting_pdf(meeting_id):
    """Generate and download a PDF summary of the meeting"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        meeting = get_meeting_by_id(meeting_id, user_id)
        if not meeting:
            return jsonify({"error": "Meeting not found"}), 404
            
        from utils.pdf_generator import generate_meeting_pdf
        from flask import make_response
        
        pdf_bytes = generate_meeting_pdf(meeting)
        
        response = make_response(pdf_bytes)
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename=f"Meeting_Report_{meeting_id}.pdf")
        return response
        
    except Exception as e:
        print(f"PDF Download Error: {e}")
        return jsonify({"error": "Internal failure generating PDF"}), 500

@app.route('/api/meetings/<meeting_id>', methods=['DELETE'])
def delete_meeting_endpoint(meeting_id):
    """Delete a meeting"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        success = delete_meeting(meeting_id, user_id)
        if success:
            return jsonify({"message": "Meeting deleted"}), 200
        else:
            return jsonify({"error": "Meeting not found"}), 404
    except Exception as e:
        return jsonify({"error": "Invalid token"}), 401

@app.route('/api/meetings/<meeting_id>/end', methods=['POST'])
def end_meeting(meeting_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        existing = get_meeting_by_id(meeting_id, user_id)
        if not existing:
            return jsonify({"error": "Meeting not found"}), 404
        body = request.get_json(silent=True) or {}
        transcript = body.get('transcript', existing.get('transcript') or '')
        summary = body.get('summary') or (summarize_text(transcript) if transcript else "No summary available.")
        action_items = body.get('action_items') or extract_action_items(f"{summary}\n{transcript}")
        updated = mark_meeting_completed(
            meeting_id=meeting_id,
            user_id=user_id,
            transcript=transcript,
            summary=summary,
            action_items=action_items,
            ended_at=datetime.utcnow(),
        )
        for item in action_items:
            title = item.get("title") if isinstance(item, dict) else str(item)
            if title:
                create_task(user_id, title, source_type="meeting", source_id=meeting_id)
        return jsonify({"meeting": updated, "status": "completed"}), 200
    except Exception:
        return jsonify({"error": "Failed to end meeting"}), 500

@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    auth_header = request.headers.get('Authorization')
    if not auth_header: return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        schedules = get_user_schedules(payload['user_id'])
        return jsonify({"schedules": schedules}), 200
    except: return jsonify({"error": "Invalid token"}), 401

@app.route('/api/schedules', methods=['POST'])
def add_schedule():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        data = request.get_json(silent=True) or {}
        user_id = payload['user_id']
        user_email = payload.get('email')
        detected_tz = request.headers.get('X-User-Timezone') or data.get('timezone')

        # Ensure defaults exist and include detected timezone for first-time settings.
        get_or_create_user_settings(user_id, detected_timezone=detected_tz)

        print(
            f"[SCHEDULE REQUEST] user_id={user_id} title={data.get('title')} "
            f"start_time={data.get('start_time')} timezone={detected_tz}"
        )
        
        schedule = create_schedule(
            user_id=user_id,
            title=data.get('title'),
            start_time=data.get('start_time'),
            participants=data.get('participants'),
            duration_minutes=data.get('duration_minutes'),
            request_timezone=detected_tz,
        )
        
        settings = get_or_create_user_settings(user_id)

        # Trigger In-App Notification
        if settings.notifications_enabled:
            create_notification(user_id, f"Project Meeting scheduled: {data.get('title')}", type='schedule')
        
        # Trigger Email Notification
        if user_email and settings.email_notifications_enabled:
            send_notification_email(user_email, data.get('title'), data.get('start_time'), type='schedule')

        return jsonify({"schedule": schedule}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"[SCHEDULE ERROR] {e}")
        return jsonify({"error": "Failed to schedule meeting"}), 500

@app.route('/api/schedules/<schedule_id>', methods=['DELETE'])
def cancel_schedule(schedule_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header: return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        success = delete_schedule(schedule_id, payload['user_id'])
        if success: return jsonify({"message": "Cancelled"}), 200
        return jsonify({"error": "Not found"}), 404
    except: return jsonify({"error": "Invalid token"}), 401

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    auth_header = request.headers.get('Authorization')
    if not auth_header: return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        settings = get_or_create_user_settings(payload['user_id'])
        if not settings.notifications_enabled:
            return jsonify({"notifications": []}), 200
    except Exception as e:
        return jsonify({"error": f"Auth error: {str(e)}"}), 401
        
    try:
        notifs = get_user_notifications(payload['user_id'])
        return jsonify({"notifications": notifs}), 200
    except Exception as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

@app.route('/api/notifications/<notif_id>/read', methods=['POST'])
def mark_read(notif_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header: return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        success = mark_as_read(notif_id, payload['user_id'])
        return jsonify({"success": success}), 200
    except: return jsonify({"error": "Invalid token"}), 401

@app.route('/api/notifications/<notif_id>/read', methods=['PUT'])
def mark_read_put(notif_id):
    return mark_read(notif_id)

@app.route('/api/notifications', methods=['DELETE'])
def clear_all_notifications():
    auth_header = request.headers.get('Authorization')
    if not auth_header: return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        from models.notification import clear_user_notifications
        payload = decode_token(token)
        count = clear_user_notifications(payload['user_id'])
        return jsonify({"success": True, "deleted_count": count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/email/send', methods=['POST'])
def email_send():
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
    recipient = (data.get('to') or '').strip()
    subject = (data.get('subject') or 'Message from Auralis').strip()
    body = (data.get('body') or '').strip()
    approved = bool(data.get('approved', False))
    if not recipient or not body:
        return jsonify({"error": "to and body are required"}), 400

    import re
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", recipient):
        return jsonify({"error": "Invalid recipient email address format."}), 400

    settings = get_or_create_user_settings(user_id)
    if settings.require_email_approval and not _can_auto_send_email(settings, recipient, approved):
        return jsonify({"error": "Email requires explicit approval"}), 400

    try:
        send_email_custom(recipient, subject, body)
        category = categorize_email(subject, body)
        summary = summarize_text(body) if len(body) > 80 else body
        row = create_email_entry(
            user_id=user_id,
            subject=subject,
            body=body,
            summary=summary,
            recipient=recipient,
            direction='outgoing',
            category=category,
            approved=approved,
        )
        add_memory(user_id, f"EMAIL_DRAFT: {subject} | {summary}")
        for item in extract_action_items(f"{subject}\n{body}"):
            create_task(user_id, item["title"], source_type="email", source_id=row["id"])
        return jsonify({"email": row, "status": "sent"}), 200
    except Exception as e:
        return jsonify({"error": "Failed to send email"}), 500

@app.route('/api/email/action', methods=['POST'])
def email_action():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    data = request.get_json(silent=True) or {}
    email_id = data.get('email_id')
    action = data.get('action') # 'star', 'unstar', 'delete', 'undelete', 'read', 'unread'
    
    from models.email import Email
    email = Email.query.filter_by(id=email_id, user_id=user_id).first()
    if not email:
        return jsonify({"error": "Email not found"}), 404
        
    if action == 'star': email.is_starred = True
    elif action == 'unstar': email.is_starred = False
    elif action == 'delete': email.is_deleted = True
    elif action == 'undelete': email.is_deleted = False
    elif action == 'read': email.unread = False
    elif action == 'unread': email.unread = True
    
    db.session.commit()
    return jsonify({"success": True, "email": email.to_dict()}), 200

@app.route('/api/email/list', methods=['GET'])
def email_list():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        
        # Sync from IMAP source
        try:
            from utils.email_reader import fetch_recent_emails
            from models.email import Email, create_email_entry
            from utils.assistant_intelligence import categorize_email
            
            recent_source = fetch_recent_emails(limit=40)
            for res in recent_source:
                # Check for existing
                exists = Email.query.filter_by(
                    user_id=user_id,
                    subject=res['subject'],
                    sender=res['from']
                ).first()
                if not exists:
                    cat = categorize_email(res['subject'], res['body'])
                    # Parse ISO string back to datetime for SQLAlchemy compatibility
                    parsed_date = res.get('parsed_date')
                    if isinstance(parsed_date, str):
                        try:
                            from datetime import datetime
                            parsed_dt = datetime.fromisoformat(parsed_date.replace("Z", "+00:00")).replace(tzinfo=None)
                        except Exception:
                            parsed_dt = datetime.utcnow()
                    else:
                        parsed_dt = datetime.utcnow()

                    row = Email(
                        user_id=user_id,
                        subject=res['subject'],
                        body=res['body'],
                        sender=res['from'],
                        direction='incoming',
                        category=cat,
                        summary=res['body'][:120],
                        created_at=parsed_dt
                    )
                    db.session.add(row)
            db.session.commit()
        except Exception as e:
            print(f"[EMAIL SYNC ERROR] {e}")

        emails = get_user_emails(user_id)
        return jsonify({"emails": emails}), 200
    except:
        return jsonify({"error": "Invalid token"}), 401

@app.route('/api/productivity/stats', methods=['GET'])
def get_productivity_stats():
    """Return today's productivity stats for the dashboard."""
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
        today_metrics = get_or_create_daily_metrics(user_id)
        task_metrics = get_task_metrics(user_id)
        weekly_data = get_user_metrics(user_id, limit=7)

        # Build weekly activity chart data (oldest first)
        weekly_activity = [
            {
                "day": m["record_date"][-5:],  # MM-DD
                "tasks": m["tasks_completed"]
            }
            for m in reversed(weekly_data)
        ]

        return jsonify({
            "productivity_score": int(today_metrics.focus_score),
            "tasks_completed_today": today_metrics.tasks_completed,
            "pending_tasks": task_metrics.get("pending", 0),
            "most_active_time": "Morning",  # Placeholder; real logic can be derived from behavior logs
            "weekly_activity": weekly_activity,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/digital-twin', methods=['GET'])
def get_digital_twin_suggestions():
    """Return proactive AI suggestions for the dashboard."""
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
        from utils.assistant_intelligence import suggest_proactive_items
        from models.email import get_user_emails
        from services.ml.habit_cluster import habit_engine
        from models.productivity_metrics import get_or_create_daily_metrics
        from models.task import Task
        from meeting_system.models import MeetingV2
        from datetime import date

        # ── Dynamic productivity score ──────────────────────────────────
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_end   = datetime.combine(date.today(), datetime.max.time())

        # Count tasks completed or in-progress today (updated today)
        tasks_done_today = Task.query.filter(
            Task.user_id == user_id,
            Task.status.in_(["completed", "in-progress"]),
            Task.updated_at >= today_start,
            Task.updated_at <= today_end,
        ).count()

        # Count total tasks created (to gauge activity)
        tasks_created_today = Task.query.filter(
            Task.user_id == user_id,
            Task.created_at >= today_start,
            Task.created_at <= today_end,
        ).count()

        # Count meetings that started today (any status)
        meetings_today = MeetingV2.query.filter(
            MeetingV2.user_id == user_id,
            MeetingV2.scheduled_start_at >= today_start,
            MeetingV2.scheduled_start_at <= today_end,
        ).count()

        # Score formula (generous for power users with many tasks/meetings):
        # - Tasks completed/in-progress today: each worth 14 pts, max 70
        # - Meetings today: each worth 5 pts, max 20
        # - Baseline for any activity: 10 pts
        task_points    = min(70, tasks_done_today * 14)
        meeting_points = min(20, meetings_today   * 5)
        baseline       = 10 if (tasks_created_today + meetings_today) > 0 else 0
        score = min(100, task_points + meeting_points + baseline)

        # Persist the score so /api/analytics can also reuse it
        metrics = get_or_create_daily_metrics(user_id)
        metrics.tasks_completed   = tasks_done_today
        metrics.meetings_attended = meetings_today
        metrics.focus_score       = float(score)
        db.session.commit()
        # ────────────────────────────────────────────────────────────────

        schedules    = get_user_schedules(user_id)
        tasks        = get_user_tasks(user_id, include_completed=False, limit=50)
        emails       = get_user_emails(user_id, limit=20)
        suggestions  = suggest_proactive_items(schedules, tasks, emails)
        recommendations = habit_engine.get_autonomous_recommendations(user_id)

        resp_payload = {
            "suggestions": suggestions,
            "patterns": [
                "You complete 60% of tasks before noon",
                "Tuesday is your most meeting-heavy day"
            ],
            "predictions": [
                "High likelihood of clearing inbox tomorrow",
                "Meeting overload risk on Thursday"
            ],
            "recommendations": recommendations if recommendations else ["Block 2 hours of focus time tomorrow"],
            "productivity_score": score,
        }
        return jsonify(resp_payload), 200
    except Exception as e:
        return jsonify({"error": str(e), "suggestions": []}), 500



# ── Tasks ──────────────────────────────────────────────────────────────
@app.route('/api/tasks', methods=['GET'])
def v1_get_tasks():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    tasks = get_user_tasks(user_id)
    metrics = get_task_metrics(user_id)
    return jsonify({"tasks": tasks, "metrics": metrics}), 200


@app.route('/api/tasks', methods=['POST'])
def v1_create_task():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    due_at = None
    if data.get('due_at'):
        try:
            from datetime import datetime as _dt
            due_at = _dt.fromisoformat(data['due_at'].replace('Z', '+00:00'))
        except Exception:
            pass
    task = create_task(
        user_id=user_id,
        title=title,
        source_type='manual',
        priority=data.get('priority', 'normal'),
        description=data.get('description'),
        due_at=due_at,
    )
    return jsonify({"task": task}), 201


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def v1_update_task(task_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    data = request.get_json(silent=True) or {}
    task = update_task(task_id, user_id, **data)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"task": task}), 200


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def v1_delete_task(task_id):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    ok = delete_task(task_id, user_id)
    if not ok:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"message": "Task deleted"}), 200


@app.route('/api/v1/tasks/suggestions', methods=['GET'])
def v1_task_suggestions():
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
        from utils.assistant_intelligence import suggest_proactive_items
        tasks = get_user_tasks(user_id, include_completed=False, limit=50)
        suggestions = suggest_proactive_items([], tasks, [])
        return jsonify({"suggestions": suggestions}), 200
    except Exception as e:
        return jsonify({"suggestions": [], "error": str(e)}), 200


# ── Notifications test ─────────────────────────────────────────────────────
@app.route('/api/notifications/test', methods=['POST'])
def create_test_notification():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    notif = create_notification(user_id, "Test notification from Auralis", type='system')
    return jsonify({"notification": notif}), 201


# ── AI ask ─────────────────────────────────────────────────────────────────
@app.route('/api/ai/ask', methods=['POST'])
def ai_ask():
    """Simple one-shot AI question endpoint."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        decode_token(token)
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or data.get('message') or '').strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    try:
        answer = ai_service.generate_content(question)
        return jsonify({"answer": answer or "No response generated."}), 200
    except Exception as e:
        return jsonify({"answer": "I'm currently unavailable. Please try again later.", "error": str(e)}), 200


# ── Meeting agent stubs ────────────────────────────────────────────────────
@app.route('/api/agent/ask', methods=['POST'])
def agent_ask():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        decode_token(token)
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    data = request.get_json(silent=True) or {}
    query = (data.get('query') or data.get('message') or '').strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    try:
        answer = ai_service.generate_content(f"Meeting assistant: {query}")
        return jsonify({"response": answer or "I couldn't generate a response."}), 200
    except Exception as e:
        return jsonify({"response": "Agent unavailable.", "error": str(e)}), 200


@app.route('/api/agent/draft-email', methods=['POST'])
def agent_draft_email():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        decode_token(token)
    except Exception:
        return jsonify({"error": "Invalid token"}), 401
    data = request.get_json(silent=True) or {}
    context = data.get('context', '')
    prompt = f"Draft a professional follow-up email for this meeting context: {context}"
    try:
        draft = ai_service.generate_content(prompt)
        return jsonify({"draft": draft or "Draft unavailable."}), 200
    except Exception as e:
        return jsonify({"draft": "", "error": str(e)}), 200


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    print(f" * [Auralis] Booting system on port {port}...")
    print(f" * [Auralis] NODE_ENV: {os.getenv('NODE_ENV', 'development')}")
    
    try:
        from eventlet import spawn
        spawn(proactive_worker)
        spawn(reminder_worker)
        spawn(daily_digest_worker)
        print(" * [Auralis] Neural agent and reminder systems initialized.")
    except Exception as e:
        print(f" ! [Auralis] Background worker initialization failed: {e}")

    # Use standard app.run if socketio.run is failing for some reason, 
    # but normally socketio.run is required for websockets.
    try:
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        if "10048" in str(e) or "EADDRINUSE" in str(e):
            print(f"\n!!! CRITICAL STARTUP ERROR: Port {port} is already in use.")
            print(f"!!! Please run 'python scripts/cleanup_port.py' to clear the zombie process.\n")
        else:
            print(f" !!! CRITICAL STARTUP ERROR: {e}")
