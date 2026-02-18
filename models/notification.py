from database import db
from datetime import datetime

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    type = db.Column(db.String(20), default='info')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'message': self.message,
            'type': self.type,
            'created_at': self.created_at.isoformat(),
            'is_read': self.is_read
        }

def create_notification(user_id, message, type='info'):
    notif = Notification(user_id=user_id, message=message, type=type)
    db.session.add(notif)
    db.session.commit()
    return notif.to_dict()

def get_user_notifications(user_id, only_unread=True):
    query = Notification.query.filter_by(user_id=user_id)
    if only_unread:
        query = query.filter_by(is_read=False)
    
    notifs = query.order_by(Notification.created_at.desc()).limit(20).all()
    return [n.to_dict() for n in notifs]

def mark_as_read(notif_id, user_id):
    notif = Notification.query.filter_by(id=notif_id, user_id=user_id).first()
    if notif:
        notif.is_read = True
        db.session.commit()
        return True
    return False
