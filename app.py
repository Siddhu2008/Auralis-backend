import os
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from datetime import datetime
from flask_cors import CORS
from dotenv import load_dotenv
from auth import auth_bp
from assistant import assistant_bp
from profile_bp import profile_bp
from settings_bp import settings_bp
from flask_socketio import SocketIO
from socket_events import register_socket_events
from meeting_system.realtime import register_meeting_socket_events
from meeting_system.routes import meeting_bp
import meeting_system.models  # noqa: F401
from utils.summarizer import summarize_text
from utils.jwt_handler import decode_token
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
from models.task import create_task, get_task_metrics, get_user_tasks
from utils.email_handler import send_email_custom
from utils.assistant_intelligence import categorize_email, extract_action_items

from database import db, init_db, ensure_database_schema
import models.email  # noqa: F401
import models.ai_memory  # noqa: F401
import models.task  # noqa: F401

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
try:
    init_db(app)
    ensure_database_schema(app)
except Exception as db_err:
    print(f"[CRITICAL ERROR] Database initialization failed: {db_err}")
    import traceback
    print(traceback.format_exc())
    # We continue so at least the health check can respond

# CORS Configuration
# Use specific origins for credentials support (Wildcard "*" doesn't work with credentials)
cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
if cors_origins_env:
    FRONTEND_ORIGINS = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
else:
    FRONTEND_ORIGINS = [
        "https://auralis-frontend.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

# Global CORS
CORS(app, resources={r"/*": {"origins": FRONTEND_ORIGINS}}, supports_credentials=True)

socketio = SocketIO(
    app, 
    cors_allowed_origins=FRONTEND_ORIGINS, 
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25
)

register_socket_events(socketio)
register_meeting_socket_events(socketio)

app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(assistant_bp, url_prefix='/api/assistant')
app.register_blueprint(profile_bp, url_prefix='/api/profile')
app.register_blueprint(settings_bp, url_prefix='/api/settings')
app.register_blueprint(meeting_bp, url_prefix='/api/v2/meetings')



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
    error_details = traceback.format_exc()
    print(f"[UNHANDLED ERROR] {error}")
    print(error_details)
    return jsonify({
        "error": "Internal server error",
        "details": str(error) if app.debug else "Please check server logs"
    }), 500



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

@app.route('/api/dashboard/overview', methods=['GET'])
def dashboard_overview():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        meetings = get_user_meetings(user_id)
        completed_meetings = [m for m in meetings if (m.get("status") or "completed") == "completed"]
        weekly = meetings[:20]
        weekly_hours = 0.0
        for m in weekly:
            duration = (m.get("duration") or "").lower().replace(" ", "")
            if duration.endswith("m"):
                try:
                    weekly_hours += int(duration[:-1]) / 60.0
                except Exception:
                    pass
            elif duration.endswith("h"):
                try:
                    weekly_hours += float(duration[:-1])
                except Exception:
                    pass
        return jsonify({
            "meetings_this_week": len(weekly),
            "completed_meetings": len(completed_meetings),
            "weekly_meeting_hours": round(weekly_hours, 2),
            "task_metrics": get_task_metrics(user_id),
            "email_metrics": get_email_metrics(user_id),
            "pending_tasks": get_user_tasks(user_id, include_completed=False, limit=10),
            "ai_usage": {
                "assistant_queries_last_7d": 0,
                "summaries_generated": len([m for m in meetings if m.get("summary")]),
            }
        }), 200
    except Exception:
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
                "title": meeting.get("title"),
                "date": meeting.get("date"),
                "participants": participants,
                "duration": meeting.get("duration", "N/A"),
                "summary": meeting.get("summary"),
                "transcript": meeting.get("transcript"),
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

@app.route('/api/email/list', methods=['GET'])
def email_list():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
        emails = get_user_emails(user_id)
        return jsonify({"emails": emails}), 200
    except:
        return jsonify({"error": "Invalid token"}), 401

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
