from database import db
from datetime import datetime

class ActionLog(db.Model):
    __tablename__ = 'action_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False) # e.g., 'schedule', 'email', 'task'
    action_data = db.Column(db.JSON, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # BEHAVIORAL METADATA (Digital Twin)
    context_label = db.Column(db.String(100)) # e.g., 'high_stress', 'weekend', 'quick_query'
    interaction_style = db.Column(db.String(50)) # e.g., 'concise', 'verbose', 'formal'

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action_type": self.action_type,
            "action_data": self.action_data,
            "timestamp": self.timestamp.isoformat(),
            # Digital Twin fields
            "context_label": self.context_label,
            "interaction_style": self.interaction_style,
        }

def log_action(user_id, action_type, action_data, context_label=None, interaction_style=None):
    log = ActionLog(
        user_id=user_id,
        action_type=action_type,
        action_data=action_data,
        context_label=context_label,
        interaction_style=interaction_style
    )
    db.session.add(log)
    db.session.commit()
    return log.to_dict()

def get_action_history(user_id, limit=20):
    logs = ActionLog.query.filter_by(user_id=user_id).order_by(ActionLog.timestamp.desc()).limit(limit).all()
    return [log.to_dict() for log in logs]
