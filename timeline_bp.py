from flask import Blueprint, jsonify, request
from models.task import Task
from meeting_system.models import MeetingV2
from utils.jwt_handler import decode_token

timeline_bp = Blueprint('timeline', __name__)

@timeline_bp.route('/api/timeline', methods=['GET'])
def get_unified_timeline():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        user_id = payload['user_id']
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    status_filter = request.args.get('status', 'pending')  # pending, completed, all
    
    
    # 2. Fetch Tasks
    tasks_q = Task.query.filter_by(user_id=user_id)
    if status_filter == 'pending':
        tasks_q = tasks_q.filter(Task.status != 'completed')
    elif status_filter == 'completed':
        tasks_q = tasks_q.filter_by(status='completed')
    
    tasks = tasks_q.all()
    
    # 3. Fetch Meetings
    meetings_q = MeetingV2.query.filter_by(user_id=user_id)
    # Meetings don't have a simple pending/completed status in the same way, 
    # but we'll show scheduled ones as pending and ended ones as completed.
    if status_filter == 'pending':
        meetings_q = meetings_q.filter(MeetingV2.status == 'scheduled')
    elif status_filter == 'completed':
        meetings_q = meetings_q.filter(MeetingV2.status == 'ended')
    
    meetings = meetings_q.all()
    
    timeline = []
    
        
    for t in tasks:
        timeline.append({
            "id": f"task_{t.id}",
            "original_id": t.id,
            "title": t.title,
            "time": t.due_at.isoformat() if t.due_at else None,
            "status": t.status,
            "type": "task",
            "priority": t.priority
        })
        
    for m in meetings:
        timeline.append({
            "id": f"meeting_{m.id}",
            "original_id": m.id,
            "title": m.title or "Untitled Meeting",
            "time": m.scheduled_start_at.isoformat() if m.scheduled_start_at else None,
            "status": "pending" if m.status == "scheduled" else "completed",
            "type": "meeting",
            "priority": "high",
            "meeting_code": m.meeting_code
        })
        
    # Sort by time
    def get_time(item):
        if not item['time']: return "9999-12-31"
        return item['time']
        
    timeline.sort(key=get_time)
    
    return jsonify(timeline)
