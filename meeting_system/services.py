import os
import random
import string
from datetime import datetime, timedelta, timezone

from database import db
from meeting_system.models import (
    Meeting,
    MeetingActionItem,
    MeetingChatMessage,
    MeetingDecision,
    MeetingParticipant,
    MeetingRecording,
    MeetingSummary,
    MeetingTranscript,
)
from models.user import User
from utils.ai_response import generate_answer
from utils.calendar_helper import create_google_calendar_event
from utils.email_handler import send_notification_email


MEETING_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_unique_meeting_code(length=8):
    for _ in range(20):
        code = "".join(random.choice(MEETING_CODE_ALPHABET) for _ in range(length))
        if not Meeting.query.filter_by(meeting_code=code).first():
            return code
    raise RuntimeError("Could not generate a unique meeting code")


def build_meeting_link(base_url, meeting_code):
    safe_base = (base_url or "").rstrip("/")
    return f"{safe_base}/meeting/{meeting_code}"


def validate_schedule_window(start_at, duration_minutes, buffer_minutes=10):
    now = _utc_now()
    if start_at < now:
        raise ValueError("Meeting time cannot be in the past.")

    if duration_minutes < 15 or duration_minutes > 480:
        raise ValueError("Duration must be between 15 and 480 minutes.")

    end_at = start_at + timedelta(minutes=duration_minutes)
    return end_at, timedelta(minutes=max(0, buffer_minutes))


def ensure_no_schedule_conflict(host_user_id, start_at, end_at, buffer_td):
    existing = (
        Meeting.query.filter(
            Meeting.user_id == host_user_id,
            Meeting.status.in_(["scheduled", "live"]),
            Meeting.scheduled_start_at.isnot(None),
            Meeting.scheduled_end_at.isnot(None),
        )
        .order_by(Meeting.scheduled_start_at.asc())
        .all()
    )

    new_start = start_at - buffer_td
    new_end = end_at + buffer_td
    for item in existing:
        if item.scheduled_start_at <= new_end and item.scheduled_end_at >= new_start:
            raise ValueError("Meeting conflicts with an existing schedule.")


def create_scheduled_meeting(
    *,
    host_user_id,
    title,
    scheduled_start_at,
    duration_minutes,
    attendee_emails=None,
    waiting_room_enabled=True,
    allow_participant_screen_share=True,
    frontend_base_url=None,
):
    meeting_code = generate_unique_meeting_code()
    meeting_link = build_meeting_link(frontend_base_url, meeting_code)
    end_at, buffer_td = validate_schedule_window(scheduled_start_at, duration_minutes)
    ensure_no_schedule_conflict(host_user_id, scheduled_start_at, end_at, buffer_td)

    meeting = Meeting(
        user_id=host_user_id,
        title=title,
        meeting_code=meeting_code,
        meeting_link=meeting_link,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=end_at,
        waiting_room_enabled=waiting_room_enabled,
        allow_participant_screen_share=allow_participant_screen_share,
        status="scheduled",
    )
    db.session.add(meeting)
    db.session.flush()

    host_user = User.query.get(host_user_id)
    host_participant = MeetingParticipant(
        meeting_id=meeting.id,
        user_id=host_user_id,
        display_name=(host_user.name if host_user else "Host"),
        email=(host_user.email if host_user else None),
        role="host",
        status="admitted",
        joined_at=None,
    )
    db.session.add(host_participant)

    attendee_emails = attendee_emails or []
    for email in attendee_emails:
        db.session.add(
            MeetingParticipant(
                meeting_id=meeting.id,
                user_id=None,
                display_name=email.split("@")[0],
                email=email,
                role="participant",
                status="invited",
            )
        )

    db.session.add(MeetingSummary(meeting_id=meeting.id))
    db.session.commit()

    if attendee_emails:
        for email in attendee_emails:
            send_notification_email(email, title, scheduled_start_at.isoformat(), type="schedule")

    try:
        if host_user and host_user.email:
            create_google_calendar_event(
                host_user.email,
                title=title,
                start_time=scheduled_start_at.isoformat(),
                meeting_link=meeting_link,
                attendees=attendee_emails,
                end_time=end_at.isoformat(),
            )
    except Exception as exc:
        # Keep schedule creation durable even if Google Calendar fails.
        print(f"[calendar] failed to create event for meeting={meeting.id}: {exc}")

    return meeting


def upsert_live_summary(meeting_id, live_notes, transcript_tail):
    summary = MeetingSummary.query.filter_by(meeting_id=meeting_id).first()
    if not summary:
        summary = MeetingSummary(meeting_id=meeting_id)
        db.session.add(summary)

    prompt = (
        "Create a concise live meeting summary with key points, decisions, action items,"
        " deadlines, and tone. Existing summary follows.\n\n"
        f"Existing summary:\n{live_notes}\n\nRecent transcript:\n{transcript_tail}"
    )
    ai_summary = generate_answer([], prompt)
    summary.live_summary = ai_summary
    db.session.commit()
    return summary


def persist_chat_message(meeting_id, sender_user_id, sender_name, message, message_type="text", metadata=None):
    entry = MeetingChatMessage(
        meeting_id=meeting_id,
        sender_user_id=sender_user_id,
        sender_name=sender_name,
        message=message,
        message_type=message_type,
        meta=metadata or {},
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def append_transcript(meeting_id, speaker_name, speaker_user_id, transcript_text):
    segment = MeetingTranscript(
        meeting_id=meeting_id,
        speaker_name=speaker_name,
        speaker_user_id=speaker_user_id,
        transcript_text=transcript_text,
    )
    db.session.add(segment)
    db.session.commit()
    return segment


def attach_recording(meeting_id, recording_url, storage_key=None, provider="s3", started_at=None, ended_at=None):
    record = MeetingRecording.query.filter_by(meeting_id=meeting_id).first()
    if not record:
        record = MeetingRecording(meeting_id=meeting_id, recording_url=recording_url)
        db.session.add(record)
    record.recording_url = recording_url
    record.storage_key = storage_key
    record.storage_provider = provider
    record.started_at = started_at
    record.ended_at = ended_at
    db.session.commit()
    return record


def complete_meeting(meeting_id, final_summary, tone=None, action_items=None, decisions=None):
    meeting = Meeting.query.get(meeting_id)
    if not meeting:
        raise ValueError("Meeting not found.")

    meeting.status = "ended"
    meeting.ended_at = _utc_now()

    summary = MeetingSummary.query.filter_by(meeting_id=meeting_id).first()
    if not summary:
        summary = MeetingSummary(meeting_id=meeting_id)
        db.session.add(summary)

    summary.final_summary = final_summary
    summary.overall_tone = tone
    summary.action_items = action_items or []
    summary.decisions = decisions or []

    for item in action_items or []:
        db.session.add(
            MeetingActionItem(
                meeting_id=meeting_id,
                title=item.get("title", "Action item"),
                assigned_to_name=item.get("assigned_to_name"),
                due_date=_parse_iso_datetime(item.get("due_date")) if item.get("due_date") else None,
            )
        )

    for decision in decisions or []:
        db.session.add(
            MeetingDecision(
                meeting_id=meeting_id,
                decision_text=decision.get("text", "Decision"),
            )
        )

    db.session.commit()
    return meeting


def _parse_iso_datetime(raw):
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)


def find_meeting_by_code_or_id(code_or_id):
    meeting = None
    if str(code_or_id).isdigit():
        meeting = Meeting.query.get(int(code_or_id))
    if meeting:
        return meeting
    return Meeting.query.filter_by(meeting_code=str(code_or_id).upper()).first()


def serialize_meeting_bundle(meeting):
    participants = MeetingParticipant.query.filter_by(meeting_id=meeting.id).all()
    transcripts = (
        MeetingTranscript.query.filter_by(meeting_id=meeting.id)
        .order_by(MeetingTranscript.event_ts.asc())
        .all()
    )
    chats = (
        MeetingChatMessage.query.filter_by(meeting_id=meeting.id)
        .order_by(MeetingChatMessage.created_at.asc())
        .all()
    )
    summary = MeetingSummary.query.filter_by(meeting_id=meeting.id).first()
    recording = MeetingRecording.query.filter_by(meeting_id=meeting.id).first()

    started = meeting.started_at or meeting.scheduled_start_at
    ended = meeting.ended_at
    duration_seconds = None
    if started and ended:
        duration_seconds = int((ended - started).total_seconds())

    return {
        "meeting": {
            "id": meeting.id,
            "title": meeting.title,
            "meeting_code": meeting.meeting_code,
            "meeting_link": meeting.meeting_link,
            "host_user_id": meeting.user_id,
            "scheduled_start_at": meeting.scheduled_start_at.isoformat() if meeting.scheduled_start_at else None,
            "scheduled_end_at": meeting.scheduled_end_at.isoformat() if meeting.scheduled_end_at else None,
            "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
            "ended_at": meeting.ended_at.isoformat() if meeting.ended_at else None,
            "duration_seconds": duration_seconds,
            "status": meeting.status,
            "is_locked": meeting.is_locked,
            "waiting_room_enabled": meeting.waiting_room_enabled,
            "allow_participant_screen_share": meeting.allow_participant_screen_share,
            "enable_ai_proxy": meeting.enable_ai_proxy,
        },
        "participants": [
            {
                "id": p.id,
                "user_id": p.user_id,
                "display_name": p.display_name,
                "email": p.email,
                "role": p.role,
                "status": p.status,
                "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                "left_at": p.left_at.isoformat() if p.left_at else None,
                "is_muted": p.is_muted,
                "hand_raised": p.hand_raised,
            }
            for p in participants
        ],
        "transcript": [
            {
                "speaker_name": t.speaker_name,
                "speaker_user_id": t.speaker_user_id,
                "text": t.transcript_text,
                "event_ts": t.event_ts.isoformat(),
            }
            for t in transcripts
        ],
        "chat": [
            {
                "id": m.id,
                "sender_user_id": m.sender_user_id,
                "sender_name": m.sender_name,
                "message": m.message,
                "message_type": m.message_type,
                "metadata": m.metadata,
                "created_at": m.created_at.isoformat(),
            }
            for m in chats
        ],
        "summary": {
            "live_summary": summary.live_summary if summary else None,
            "final_summary": summary.final_summary if summary else None,
            "key_points": summary.key_points if summary else [],
            "decisions": summary.decisions if summary else [],
            "action_items": summary.action_items if summary else [],
            "deadlines": summary.deadlines if summary else [],
            "overall_tone": summary.overall_tone if summary else None,
        },
        "recording": {
            "recording_url": recording.recording_url if recording else None,
            "storage_provider": recording.storage_provider if recording else None,
        },
    }


def get_reminder_targets(minutes_from_now=15):
    target_start = _utc_now() + timedelta(minutes=minutes_from_now)
    window_end = target_start + timedelta(minutes=1)

    upcoming = Meeting.query.filter(
        Meeting.status == "scheduled",
        Meeting.scheduled_start_at >= target_start,
        Meeting.scheduled_start_at < window_end,
    ).all()
    return upcoming
