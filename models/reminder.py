from database import db
from datetime import datetime

class Reminder(db.Model):
    __tablename__ = 'reminders'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    due_time = db.Column(db.String(100), nullable=False) # ISO string from frontend or AI
    status = db.Column(db.String(20), default='pending') # pending, completed, dismissed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'due_time': self.due_time,
            'status': self.status,
            'created_at': self.created_at.isoformat()
        }

def create_reminder(user_id, title, due_time):
    reminder = Reminder(
        user_id=user_id,
        title=title,
        due_time=due_time
    )
    db.session.add(reminder)
    db.session.commit()
    return reminder.to_dict()

def get_user_reminders(user_id):
    return [r.to_dict() for r in Reminder.query.filter_by(user_id=user_id, status='pending').all()]
