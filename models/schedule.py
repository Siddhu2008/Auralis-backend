from database import db
from datetime import datetime

class Schedule(db.Model):
    __tablename__ = 'schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.String(100), nullable=False) # Keep as string for ISO from frontend
    participants = db.Column(db.JSON, default=[])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='upcoming')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'start_time': self.start_time,
            'participants': self.participants,
            'created_at': self.created_at.isoformat(),
            'status': self.status
        }

def create_schedule(user_id, title, start_time, participants=None):
    schedule = Schedule(
        user_id=user_id,
        title=title,
        start_time=start_time,
        participants=participants or []
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

def update_schedule(schedule_id, user_id, title=None, start_time=None, participants=None):
    schedule = Schedule.query.filter_by(id=schedule_id, user_id=user_id).first()
    if schedule:
        if title: schedule.title = title
        if start_time: schedule.start_time = start_time
        if participants is not None: schedule.participants = participants
        db.session.commit()
        return schedule.to_dict()
    return None
