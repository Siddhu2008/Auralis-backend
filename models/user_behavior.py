from datetime import datetime
from database import db


class UserBehaviorLog(db.Model):
    __tablename__ = "user_behavior_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # Tracking dimensions
    action_type = db.Column(db.String(100), nullable=False) # e.g., 'email_sent', 'meeting_scheduled', 'login'
    active_hour = db.Column(db.Integer, nullable=False) # 0-23
    day_of_week = db.Column(db.Integer, nullable=False) # 0-6 (Monday=0)
    
    # Context
    feature_used = db.Column(db.String(100), nullable=True) # e.g., 'assistant_chat', 'dashboard'
    response_time_ms = db.Column(db.Integer, nullable=True) # relevant for UI/email response delays
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action_type": self.action_type,
            "active_hour": self.active_hour,
            "day_of_week": self.day_of_week,
            "feature_used": self.feature_used,
            "response_time_ms": self.response_time_ms,
            "created_at": self.created_at.isoformat(),
        }


def log_user_behavior(user_id, action_type, feature_used=None, response_time_ms=None):
    now = datetime.utcnow()
    row = UserBehaviorLog(
        user_id=user_id,
        action_type=action_type,
        active_hour=now.hour,
        day_of_week=now.weekday(),
        feature_used=feature_used,
        response_time_ms=response_time_ms
    )
    db.session.add(row)
    db.session.commit()
    return row.to_dict()

def get_user_behaviors(user_id, limit=500):
    rows = (
        UserBehaviorLog.query.filter_by(user_id=user_id)
        .order_by(UserBehaviorLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in rows]
