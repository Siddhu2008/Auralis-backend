import os
import eventlet
eventlet.monkey_patch()

os.environ['EVENTLET_NO_GREENDNS'] = 'yes' # Force system DNS to avoid Lookup timed out on Windows

import dns.resolver
resolver = dns.resolver.Resolver()
resolver.nameservers = ['8.8.8.8']
dns.resolver.default_resolver = resolver

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
from models.meeting import create_meeting, get_user_meetings, get_meeting_by_id, delete_meeting
from models.schedule import create_schedule, get_user_schedules, delete_schedule
from models.notification import create_notification, get_user_notifications, mark_as_read
from models.user_settings import get_or_create_user_settings

from database import db, init_db, ensure_database_schema
from flask_migrate import Migrate

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
init_db(app)
ensure_database_schema(app)

FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://auralis-frontend.vercel.app"
]
CORS(app, resources={r"/*": {"origins": FRONTEND_ORIGINS}}, supports_credentials=True)
socketio = SocketIO(
    app, 
    cors_allowed_origins=FRONTEND_ORIGINS,
    async_mode='eventlet',
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


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    return jsonify({"error": error.description or "Request failed"}), error.code


@app.errorhandler(Exception)
def handle_unexpected_exception(error):
    print(f"[UNHANDLED ERROR] {error}")
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

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'True').lower() == 'true'
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
