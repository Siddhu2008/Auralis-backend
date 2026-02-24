from datetime import datetime

from flask import Blueprint, jsonify, request

from database import db
from meeting_system.models import (
    Meeting,
    MeetingChatMessage,
    MeetingParticipant,
    WaitingRoomEntry,
)
from meeting_system.services import (
    append_transcript,
    attach_recording,
    complete_meeting,
    create_scheduled_meeting,
    find_meeting_by_code_or_id,
    persist_chat_message,
    serialize_meeting_bundle,
    upsert_live_summary,
)
from meeting_system.reminders import send_upcoming_meeting_reminders
from models.user import User
from utils.jwt_handler import decode_token, generate_meeting_access_token

meeting_bp = Blueprint("meeting_bp", __name__)


def _require_auth():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, (jsonify({"error": "Unauthorized"}), 401)
    token = auth_header.split(" ")[1]
    try:
        return decode_token(token), None
    except Exception as exc:
        return None, (jsonify({"error": str(exc)}), 401)


@meeting_bp.route("/schedule", methods=["POST"])
def schedule_meeting():
    payload, err = _require_auth()
    if err:
        return err

    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    start_raw = data.get("start_time")
    duration_minutes = int(data.get("duration_minutes", 30))
    attendee_emails = data.get("participants", [])
    if not title or not start_raw:
        return jsonify({"error": "title and start_time are required"}), 400

    try:
        start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        meeting = create_scheduled_meeting(
            host_user_id=int(payload["user_id"]),
            title=title,
            scheduled_start_at=start_dt,
            duration_minutes=duration_minutes,
            attendee_emails=attendee_emails,
            waiting_room_enabled=bool(data.get("waiting_room_enabled", True)),
            allow_participant_screen_share=bool(data.get("allow_participant_screen_share", True)),
            frontend_base_url=request.host_url.rstrip("/"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Schedule creation failed: {exc}"}), 500

    return jsonify(
        {
            "meeting_id": meeting.id,
            "meeting_code": meeting.meeting_code,
            "meeting_link": meeting.meeting_link,
            "scheduled_start_at": meeting.scheduled_start_at.isoformat() if meeting.scheduled_start_at else None,
            "status": meeting.status,
        }
    ), 201


@meeting_bp.route("/<code_or_id>/join-request", methods=["POST"])
def join_request(code_or_id):
    payload, err = _require_auth()
    if err:
        return err
    meeting = find_meeting_by_code_or_id(code_or_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404

    user_id = int(payload["user_id"])
    user = User.query.get(user_id)
    display_name = user.name if user else payload.get("name", "Guest")
    email = user.email if user else payload.get("email")

    participant = MeetingParticipant.query.filter_by(meeting_id=meeting.id, user_id=user_id).first()
    if not participant:
        participant = MeetingParticipant(
            meeting_id=meeting.id,
            user_id=user_id,
            display_name=display_name,
            email=email,
            role="participant",
            status="pending" if meeting.waiting_room_enabled else "admitted",
        )
        db.session.add(participant)
    else:
        participant.status = "pending" if meeting.waiting_room_enabled else "admitted"
    db.session.flush()

    waiting = None
    if meeting.waiting_room_enabled:
        waiting = WaitingRoomEntry(
            meeting_id=meeting.id,
            user_id=user_id,
            display_name=display_name,
            email=email,
            status="pending",
        )
        db.session.add(waiting)
    db.session.commit()

    return jsonify(
        {
            "meeting_id": meeting.id,
            "status": "pending_approval" if meeting.waiting_room_enabled else "admitted",
            "waiting_entry_id": waiting.id if waiting else None,
        }
    ), 200


@meeting_bp.route("/<int:meeting_id>/waiting-room/<int:entry_id>/decision", methods=["POST"])
def waiting_room_decision(meeting_id, entry_id):
    payload, err = _require_auth()
    if err:
        return err
    user_id = int(payload["user_id"])

    meeting = Meeting.query.get(meeting_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    if meeting.user_id != user_id:
        return jsonify({"error": "Only host can approve/reject waiting room entries"}), 403

    data = request.get_json() or {}
    decision = (data.get("decision") or "").lower()
    if decision not in {"approve", "reject"}:
        return jsonify({"error": "decision must be approve or reject"}), 400

    entry = WaitingRoomEntry.query.filter_by(id=entry_id, meeting_id=meeting_id).first()
    if not entry:
        return jsonify({"error": "Waiting room entry not found"}), 404

    entry.status = "approved" if decision == "approve" else "rejected"
    entry.resolved_by_user_id = user_id
    entry.resolved_at = datetime.utcnow()

    participant = MeetingParticipant.query.filter_by(meeting_id=meeting_id, user_id=entry.user_id).first()
    if participant:
        participant.status = "admitted" if decision == "approve" else "rejected"

    db.session.commit()
    return jsonify({"entry_id": entry.id, "status": entry.status}), 200


@meeting_bp.route("/<code_or_id>/token", methods=["POST"])
def meeting_token(code_or_id):
    payload, err = _require_auth()
    if err:
        return err

    meeting = find_meeting_by_code_or_id(code_or_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404

    user_id = int(payload["user_id"])
    participant = MeetingParticipant.query.filter_by(meeting_id=meeting.id, user_id=user_id).first()
    if not participant:
        return jsonify({"error": "Join request required"}), 403
    if participant.status not in {"admitted"} and meeting.user_id != user_id:
        return jsonify({"error": "Not approved for this meeting"}), 403

    role = "host" if meeting.user_id == user_id else participant.role
    token = generate_meeting_access_token(user_id=user_id, meeting_id=meeting.id, role=role)
    return jsonify({"meeting_access_token": token, "meeting_id": meeting.id, "role": role}), 200


@meeting_bp.route("/<int:meeting_id>/chat", methods=["POST"])
def post_chat(meeting_id):
    payload, err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400
    sender_name = data.get("sender_name") or payload.get("name") or "Participant"
    message_type = data.get("message_type", "text")
    chat = persist_chat_message(meeting_id, int(payload["user_id"]), sender_name, message, message_type=message_type)
    return jsonify({"chat_id": chat.id, "created_at": chat.created_at.isoformat()}), 201


@meeting_bp.route("/<int:meeting_id>/transcript", methods=["POST"])
def post_transcript(meeting_id):
    payload, err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    speaker_name = data.get("speaker_name") or payload.get("name") or "Participant"
    seg = append_transcript(meeting_id, speaker_name, int(payload["user_id"]), text)
    return jsonify({"transcript_id": seg.id, "event_ts": seg.event_ts.isoformat()}), 201


@meeting_bp.route("/<int:meeting_id>/summary/live", methods=["POST"])
def update_live_summary(meeting_id):
    payload, err = _require_auth()
    if err:
        return err

    data = request.get_json() or {}
    live_notes = data.get("existing_summary", "")
    transcript_tail = data.get("transcript_tail", "")
    summary = upsert_live_summary(meeting_id, live_notes, transcript_tail)
    return jsonify({"live_summary": summary.live_summary, "updated_at": summary.updated_at.isoformat()}), 200


@meeting_bp.route("/<int:meeting_id>/recording", methods=["POST"])
def register_recording(meeting_id):
    payload, err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    recording_url = data.get("recording_url")
    if not recording_url:
        return jsonify({"error": "recording_url is required"}), 400
    record = attach_recording(
        meeting_id=meeting_id,
        recording_url=recording_url,
        storage_key=data.get("storage_key"),
        provider=data.get("provider", "s3"),
    )
    return jsonify({"recording_id": record.id, "recording_url": record.recording_url}), 201


@meeting_bp.route("/<int:meeting_id>/complete", methods=["POST"])
def finalize_meeting(meeting_id):
    payload, err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    meeting = complete_meeting(
        meeting_id,
        final_summary=data.get("final_summary", ""),
        tone=data.get("overall_tone"),
        action_items=data.get("action_items", []),
        decisions=data.get("decisions", []),
    )
    return jsonify({"meeting_id": meeting.id, "status": meeting.status, "ended_at": meeting.ended_at.isoformat()}), 200


@meeting_bp.route("/past", methods=["GET"])
def list_past_meetings():
    payload, err = _require_auth()
    if err:
        return err
    user_id = int(payload["user_id"])
    meetings = (
        Meeting.query.filter(
            (Meeting.user_id == user_id) & (Meeting.status == "ended")
        )
        .order_by(Meeting.ended_at.desc())
        .all()
    )
    response = []
    for meeting in meetings:
        response.append(serialize_meeting_bundle(meeting))
    return jsonify({"meetings": response}), 200


@meeting_bp.route("/<code_or_id>", methods=["GET"])
def get_meeting_details(code_or_id):
    payload, err = _require_auth()
    if err:
        return err
    meeting = find_meeting_by_code_or_id(code_or_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    return jsonify(serialize_meeting_bundle(meeting)), 200


@meeting_bp.route("/<int:meeting_id>/chat/history", methods=["GET"])
def get_chat_history(meeting_id):
    payload, err = _require_auth()
    if err:
        return err
    rows = (
        MeetingChatMessage.query.filter_by(meeting_id=meeting_id)
        .order_by(MeetingChatMessage.created_at.asc())
        .all()
    )
    return jsonify(
        {
            "chat": [
                {
                    "id": row.id,
                    "sender_name": row.sender_name,
                    "message": row.message,
                    "message_type": row.message_type,
                    "metadata": row.metadata,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }
    ), 200


@meeting_bp.route("/reminders/dispatch", methods=["POST"])
def dispatch_reminders():
    payload, err = _require_auth()
    if err:
        return err
    sent = send_upcoming_meeting_reminders(15)
    return jsonify({"sent": sent, "requested_by": payload["user_id"]}), 200
