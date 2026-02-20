from database import db
from datetime import datetime
from models.user_settings import get_or_create_user_settings
from models.user_preference import get_preferences

class Schedule(db.Model):
    __tablename__ = 'schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.String(100), nullable=False) # Keep as string for ISO from frontend
    participants = db.Column(db.JSON, default=[])
    duration_minutes = db.Column(db.Integer, default=30, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='upcoming')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'start_time': self.start_time,
            'participants': self.participants,
            'duration_minutes': self.duration_minutes,
            'created_at': self.created_at.isoformat(),
            'status': self.status
        }

def create_schedule(user_id, title, start_time, participants=None, duration_minutes=None):
    settings = get_or_create_user_settings(user_id)

    try:
        parsed = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except Exception:
        raise ValueError("Invalid start_time format. Use ISO datetime.")

    now = datetime.utcnow().astimezone(parsed.tzinfo) if parsed.tzinfo else datetime.utcnow()
    if settings.prevent_past_dates and parsed < now:
        raise ValueError("Cannot schedule in the past.")

    weekday = parsed.strftime("%a")
    mapped_weekday = weekday[:3]
    if mapped_weekday not in (settings.working_days or []):
        raise ValueError("Selected day is outside configured working days.")

    if settings.prevent_outside_working_hours:
        slot = parsed.strftime("%H:%M")
        if slot < settings.working_hours_start or slot > settings.working_hours_end:
            raise ValueError("Selected time is outside configured working hours.")

    prefs = get_preferences(user_id)
    detect_conflicts = prefs.get("detect_conflicts", True)

    duration_minutes = duration_minutes or settings.default_meeting_duration or 30
    if detect_conflicts:
        existing = Schedule.query.filter_by(user_id=user_id, status='upcoming').all()
        new_start = parsed
        buffer_minutes = settings.buffer_time_minutes or 0
        new_end = new_start.timestamp() + ((duration_minutes + buffer_minutes) * 60)

        for item in existing:
            try:
                item_start_dt = datetime.fromisoformat(item.start_time.replace("Z", "+00:00"))
            except Exception:
                continue

            item_duration = item.duration_minutes or settings.default_meeting_duration or 30
            item_end = item_start_dt.timestamp() + ((item_duration + buffer_minutes) * 60)
            if new_start.timestamp() < item_end and new_end > item_start_dt.timestamp():
                raise ValueError("Schedule conflicts with another meeting considering buffer time.")

    schedule = Schedule(
        user_id=user_id,
        title=title,
        start_time=start_time,
        participants=participants or [],
        duration_minutes=duration_minutes,
    )
    db.session.add(schedule)
    db.session.commit()
    return schedule.to_dict()

def get_user_schedules(user_id):
    schedules = Schedule.query.filter_by(user_id=user_id, status='upcoming').order_by(Schedule.start_time.asc()).all()
    return [s.to_dict() for s in schedules]

def delete_schedule(schedule_id, user_id):
    schedule = Schedule.query.filter_by(id=schedule_id, user_id=user_id).first()
    if schedule:
        db.session.delete(schedule)
        db.session.commit()
        return True
    return False

def update_schedule(schedule_id, user_id, title=None, start_time=None, participants=None, duration_minutes=None):
    schedule = Schedule.query.filter_by(id=schedule_id, user_id=user_id).first()
    if schedule:
        if title: schedule.title = title
        if start_time: schedule.start_time = start_time
        if participants is not None: schedule.participants = participants
        if duration_minutes is not None: schedule.duration_minutes = duration_minutes
        db.session.commit()
        return schedule.to_dict()
    return None
