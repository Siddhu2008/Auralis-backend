from collections import defaultdict
from datetime import datetime

from flask import request
from flask_socketio import emit, join_room, leave_room

from database import db
from meeting_system.models import Meeting, MeetingParticipant
from meeting_system.services import append_transcript, persist_chat_message
from utils.jwt_handler import decode_meeting_access_token


class RoomState:
    def __init__(self):
        self.members = {}  # sid -> dict(user_id, name, role)
        self.waiting = {}  # sid -> dict(user_id, name)
        self.locked = False
        self.screen_share_disabled = False
        self.muted_by_host = set()
        self.co_host_user_id = None


room_states = defaultdict(RoomState)


def _room_name(meeting_id):
    return f"meeting:{meeting_id}"


def register_meeting_socket_events(socketio):
    @socketio.on("meeting:join")
    def handle_join(data):
        token = data.get("meeting_access_token")
        if not token:
            emit("meeting:error", {"message": "meeting_access_token is required"})
            return

        try:
            payload = decode_meeting_access_token(token)
        except Exception as exc:
            emit("meeting:error", {"message": str(exc)})
            return

        meeting_id = int(payload["meeting_id"])
        user_id = int(payload["sub"])
        role = payload.get("meeting_role", "participant")
        display_name = data.get("display_name") or data.get("name") or f"user-{user_id}"
        sid = request.sid

        meeting = Meeting.query.get(meeting_id)
        if not meeting:
            emit("meeting:error", {"message": "Meeting not found"})
            return
        if meeting.is_locked and role != "host":
            emit("meeting:locked", {"meeting_id": meeting_id})
            return

        room = _room_name(meeting_id)
        state = room_states[meeting_id]
        join_room(room)

        state.members[sid] = {"user_id": user_id, "name": display_name, "role": role}
        participant = MeetingParticipant.query.filter_by(meeting_id=meeting_id, user_id=user_id).first()
        if participant:
            participant.status = "admitted"
            participant.joined_at = participant.joined_at or datetime.utcnow()
            if role == "host":
                participant.role = "host"
            db.session.commit()

        if meeting.started_at is None:
            meeting.started_at = datetime.utcnow()
            meeting.status = "live"
            db.session.commit()

        emit(
            "meeting:joined",
            {
                "meeting_id": meeting_id,
                "self_sid": sid,
                "role": role,
                "participants": [
                    {"sid": psid, **p}
                    for psid, p in state.members.items()
                    if psid != sid
                ],
            },
        )
        emit(
            "meeting:participant_joined",
            {"sid": sid, "user_id": user_id, "name": display_name, "role": role},
            room=room,
            include_self=False,
        )

    @socketio.on("meeting:leave")
    def handle_leave(data):
        meeting_id = int(data.get("meeting_id"))
        room = _room_name(meeting_id)
        sid = request.sid
        state = room_states[meeting_id]

        member = state.members.pop(sid, None)
        leave_room(room)

        if member:
            participant = MeetingParticipant.query.filter_by(
                meeting_id=meeting_id,
                user_id=member["user_id"],
            ).first()
            if participant:
                participant.status = "left"
                participant.left_at = datetime.utcnow()
                db.session.commit()
            emit("meeting:participant_left", {"sid": sid, "user_id": member["user_id"]}, room=room)

        _ensure_host_failover(meeting_id, room)

    @socketio.on("meeting:signal")
    def handle_signal(data):
        target_sid = data.get("target_sid")
        payload = data.get("payload")
        emit("meeting:signal", {"from_sid": request.sid, "payload": payload}, room=target_sid)

    @socketio.on("meeting:chat")
    def handle_chat(data):
        meeting_id = int(data.get("meeting_id"))
        room = _room_name(meeting_id)
        sid = request.sid
        state = room_states[meeting_id]
        member = state.members.get(sid)
        if not member:
            emit("meeting:error", {"message": "Not in meeting room"})
            return

        message = (data.get("message") or "").strip()
        if not message:
            return
        entry = persist_chat_message(
            meeting_id,
            member["user_id"],
            member["name"],
            message,
            message_type=data.get("message_type", "text"),
            metadata=data.get("metadata") or {},
        )
        emit(
            "meeting:chat",
            {
                "id": entry.id,
                "sender_user_id": member["user_id"],
                "sender_name": member["name"],
                "message": entry.message,
                "message_type": entry.message_type,
                "metadata": entry.meta,
                "created_at": entry.created_at.isoformat(),
            },
            room=room,
        )

    @socketio.on("meeting:transcript")
    def handle_transcript(data):
        meeting_id = int(data.get("meeting_id"))
        room = _room_name(meeting_id)
        sid = request.sid
        state = room_states[meeting_id]
        member = state.members.get(sid)
        if not member:
            return
        text = (data.get("text") or "").strip()
        if not text:
            return
        segment = append_transcript(meeting_id, member["name"], member["user_id"], text)
        emit(
            "meeting:transcript",
            {
                "id": segment.id,
                "speaker_name": member["name"],
                "speaker_user_id": member["user_id"],
                "text": text,
                "event_ts": segment.event_ts.isoformat(),
            },
            room=room,
        )

    @socketio.on("meeting:raise_hand")
    def handle_raise_hand(data):
        meeting_id = int(data.get("meeting_id"))
        room = _room_name(meeting_id)
        sid = request.sid
        state = room_states[meeting_id]
        member = state.members.get(sid)
        if not member:
            return
        raised = bool(data.get("raised"))
        participant = MeetingParticipant.query.filter_by(
            meeting_id=meeting_id, user_id=member["user_id"]
        ).first()
        if participant:
            participant.hand_raised = raised
            db.session.commit()
        emit("meeting:raise_hand", {"sid": sid, "user_id": member["user_id"], "raised": raised}, room=room)

    @socketio.on("meeting:reaction")
    def handle_reaction(data):
        meeting_id = int(data.get("meeting_id"))
        room = _room_name(meeting_id)
        emit(
            "meeting:reaction",
            {"sid": request.sid, "emoji": data.get("emoji", "👍"), "ts": datetime.utcnow().isoformat()},
            room=room,
        )

    @socketio.on("meeting:host_control")
    def handle_host_control(data):
        meeting_id = int(data.get("meeting_id"))
        action = data.get("action")
        room = _room_name(meeting_id)
        state = room_states[meeting_id]
        actor = state.members.get(request.sid)
        if not actor or actor.get("role") not in {"host", "co_host"}:
            emit("meeting:error", {"message": "Only host/co-host can perform this action"})
            return

        if action == "mute_participant":
            target_sid = data.get("target_sid")
            emit("meeting:force_mute", {"reason": "Muted by host"}, room=target_sid)
            state.muted_by_host.add(target_sid)
            emit("meeting:host_control", {"action": action, "target_sid": target_sid}, room=room)
            return

        if action == "remove_participant":
            target_sid = data.get("target_sid")
            target = state.members.pop(target_sid, None)
            if target:
                emit("meeting:removed", {"reason": "Removed by host"}, room=target_sid)
                emit(
                    "meeting:participant_left",
                    {"sid": target_sid, "user_id": target["user_id"]},
                    room=room,
                )
            return

        if action == "disable_screen_share":
            state.screen_share_disabled = bool(data.get("value", True))
            emit(
                "meeting:host_control",
                {"action": action, "disabled": state.screen_share_disabled},
                room=room,
            )
            return

        if action == "lock_meeting":
            meeting = Meeting.query.get(meeting_id)
            if not meeting:
                return
            meeting.is_locked = bool(data.get("value", True))
            state.locked = meeting.is_locked
            db.session.commit()
            emit("meeting:locked_state", {"locked": meeting.is_locked}, room=room)
            return

        if action == "end_for_all":
            meeting = Meeting.query.get(meeting_id)
            if meeting:
                meeting.status = "ended"
                meeting.ended_at = datetime.utcnow()
                db.session.commit()
            emit("meeting:ended", {"meeting_id": meeting_id}, room=room)
            room_states.pop(meeting_id, None)
            return

    @socketio.on("disconnect")
    def handle_disconnect():
        sid = request.sid
        for meeting_id, state in list(room_states.items()):
            if sid not in state.members:
                continue
            room = _room_name(meeting_id)
            member = state.members.pop(sid, None)
            if member:
                participant = MeetingParticipant.query.filter_by(
                    meeting_id=meeting_id, user_id=member["user_id"]
                ).first()
                if participant:
                    participant.status = "left"
                    participant.left_at = datetime.utcnow()
                    db.session.commit()
                emit("meeting:participant_left", {"sid": sid, "user_id": member["user_id"]}, room=room)
            _ensure_host_failover(meeting_id, room)


def _ensure_host_failover(meeting_id, room):
    state = room_states[meeting_id]
    hosts = [(sid, v) for sid, v in state.members.items() if v.get("role") == "host"]
    if hosts:
        return
    candidates = [(sid, v) for sid, v in state.members.items() if v.get("role") in {"co_host", "participant"}]
    if not candidates:
        room_states.pop(meeting_id, None)
        return
    promoted_sid, promoted = candidates[0]
    promoted["role"] = "host"
    emit(
        "meeting:role_changed",
        {"sid": promoted_sid, "user_id": promoted["user_id"], "role": "host"},
        room=room,
    )
