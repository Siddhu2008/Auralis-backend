from database import db
from datetime import datetime

class Meeting(db.Model):
    __tablename__ = 'meetings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    room_id = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    transcript = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    duration = db.Column(db.String(20), default='N/A')
    participants_count = db.Column(db.Integer, default=1)
    recording_url = db.Column(db.String(500), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'room_id': self.room_id,
            'title': self.title,
            'date': self.date.isoformat(),
            'transcript': self.transcript,
            'summary': self.summary,
            'duration': self.duration,
            'participants_count': self.participants_count,
            'recording_url': self.recording_url
        }

def create_meeting(user_id, room_id, title, transcript, summary, duration='N/A', participants_count=1):
    meeting = Meeting(
        user_id=user_id,
        room_id=room_id,
        title=title,
        transcript=transcript,
        summary=summary,
        duration=duration,
        participants_count=participants_count
    )
    db.session.add(meeting)
    db.session.commit()
    return meeting.to_dict()

def get_user_meetings(user_id):
    meetings = Meeting.query.filter_by(user_id=user_id).order_by(Meeting.date.desc()).all()
    return [m.to_dict() for m in meetings]

def get_meeting_by_id(meeting_id, user_id):
    meeting = Meeting.query.filter_by(id=meeting_id, user_id=user_id).first()
    return meeting.to_dict() if meeting else None

def delete_meeting(meeting_id, user_id):
    meeting = Meeting.query.filter_by(id=meeting_id, user_id=user_id).first()
    if meeting:
        db.session.delete(meeting)
        db.session.commit()
        return True
    return False
