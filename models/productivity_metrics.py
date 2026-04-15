from datetime import datetime, date
from database import db

class ProductivityMetrics(db.Model):
    __tablename__ = "productivity_metrics"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    record_date = db.Column(db.Date, nullable=False, default=date.today)
    
    # Metric counts (Aggregated nightly or real-time)
    tasks_completed = db.Column(db.Integer, default=0)
    tasks_created = db.Column(db.Integer, default=0)
    meetings_attended = db.Column(db.Integer, default=0)
    emails_processed = db.Column(db.Integer, default=0)
    
    # Calculated AI twin score
    focus_score = db.Column(db.Float, default=0.0) # 0.0 to 100.0
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'record_date', name='uq_user_date_metrics'),)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "record_date": self.record_date.isoformat(),
            "tasks_completed": self.tasks_completed,
            "tasks_created": self.tasks_created,
            "meetings_attended": self.meetings_attended,
            "emails_processed": self.emails_processed,
            "focus_score": self.focus_score,
            "updated_at": self.updated_at.isoformat(),
        }

def get_or_create_daily_metrics(user_id):
    today = date.today()
    record = ProductivityMetrics.query.filter_by(user_id=user_id, record_date=today).first()
    if not record:
        record = ProductivityMetrics(user_id=user_id, record_date=today)
        db.session.add(record)
        db.session.commit()
    return record

def increment_metric(user_id, metric_field):
    record = get_or_create_daily_metrics(user_id)
    current_val = getattr(record, metric_field, 0)
    setattr(record, metric_field, current_val + 1)
    
    # Auto-update focus score based on a simple heuristic for now
    completed = getattr(record, 'tasks_completed', 0)
    created = getattr(record, 'tasks_created', 1) 
    base_score = min(100.0, (completed / max(1, created)) * 100.0)
    record.focus_score = round(base_score, 1)
    
    db.session.commit()
    return record.to_dict()

def get_user_metrics(user_id, limit=30):
    rows = (
        ProductivityMetrics.query.filter_by(user_id=user_id)
        .order_by(ProductivityMetrics.record_date.desc())
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in rows]
