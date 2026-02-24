from utils.email_handler import send_notification_email
from meeting_system.models import MeetingParticipant
from meeting_system.services import get_reminder_targets


def send_upcoming_meeting_reminders(minutes_before=15):
    meetings = get_reminder_targets(minutes_before)
    sent = 0

    for meeting in meetings:
        participants = MeetingParticipant.query.filter_by(meeting_id=meeting.id).all()
        for participant in participants:
            if not participant.email:
                continue
            ok = send_notification_email(
                participant.email,
                meeting.title or f"Meeting {meeting.meeting_code}",
                meeting.scheduled_start_at.isoformat() if meeting.scheduled_start_at else "",
                type="schedule",
            )
            if ok:
                sent += 1
    return sent
