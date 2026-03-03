from datetime import datetime
from database import db


class V2Meeting(db.Model):
    __tablename__ = "v2_meetings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    meeting_code = db.Column(db.String(12), nullable=True, unique=True, index=True)
    meeting_link = db.Column(db.String(500), nullable=True, unique=True)
    scheduled_start_at = db.Column(db.DateTime, nullable=True, index=True)
    scheduled_end_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    waiting_room_enabled = db.Column(db.Boolean, default=True, nullable=False)
    allow_participant_screen_share = db.Column(db.Boolean, default=True, nullable=False)
    enable_ai_proxy = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default="scheduled", nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MeetingParticipant(db.Model):
    __tablename__ = "participants"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    display_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=True, index=True)
    role = db.Column(db.String(20), default="participant", nullable=False)  # host/co_host/participant/ai_proxy
    status = db.Column(db.String(20), default="invited", nullable=False)  # invited/pending/admitted/rejected/left
    joined_at = db.Column(db.DateTime, nullable=True)
    left_at = db.Column(db.DateTime, nullable=True)
    is_muted = db.Column(db.Boolean, default=False, nullable=False)
    hand_raised = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MeetingTranscript(db.Model):
    __tablename__ = "meeting_transcripts"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, index=True)
    speaker_name = db.Column(db.String(120), nullable=True)
    speaker_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    transcript_text = db.Column(db.Text, nullable=False)
    event_ts = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class MeetingSummary(db.Model):
    __tablename__ = "meeting_summaries"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, unique=True, index=True)
    live_summary = db.Column(db.Text, nullable=True)
    final_summary = db.Column(db.Text, nullable=True)
    key_points = db.Column(db.JSON, default=list, nullable=False)
    decisions = db.Column(db.JSON, default=list, nullable=False)
    action_items = db.Column(db.JSON, default=list, nullable=False)
    deadlines = db.Column(db.JSON, default=list, nullable=False)
    overall_tone = db.Column(db.String(50), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MeetingRecording(db.Model):
    __tablename__ = "meeting_recordings"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, unique=True, index=True)
    storage_provider = db.Column(db.String(30), default="s3", nullable=False)
    recording_url = db.Column(db.String(1000), nullable=False)
    storage_key = db.Column(db.String(500), nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MeetingChatMessage(db.Model):
    __tablename__ = "meeting_chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, index=True)
    sender_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sender_name = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default="text", nullable=False)  # text/file/emoji/system
    meta = db.Column(db.JSON, default=dict, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class MeetingActionItem(db.Model):
    __tablename__ = "meeting_action_items"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    assigned_to_name = db.Column(db.String(120), nullable=True)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    due_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default="open", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MeetingDecision(db.Model):
    __tablename__ = "meeting_decisions"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, index=True)
    decision_text = db.Column(db.Text, nullable=False)
    decided_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


class WaitingRoomEntry(db.Model):
    __tablename__ = "meeting_waiting_room_entries"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("v2_meetings.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    display_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=True, index=True)
    socket_session_id = db.Column(db.String(128), nullable=True, index=True)
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
