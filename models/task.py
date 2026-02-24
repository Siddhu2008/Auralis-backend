from datetime import datetime
from database import db


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    source_type = db.Column(db.String(30), nullable=False, default="manual")  # email/meeting/assistant/manual
    source_id = db.Column(db.String(64), nullable=True)
    title = db.Column(db.String(500), nullable=False)
    due_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending/completed/cancelled
    priority = db.Column(db.String(20), nullable=False, default="normal")  # low/normal/high
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "title": self.title,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def create_task(user_id, title, source_type="manual", source_id=None, due_at=None, priority="normal"):
    row = Task(
        user_id=user_id,
        title=title,
        source_type=source_type,
        source_id=str(source_id) if source_id is not None else None,
        due_at=due_at,
        priority=priority if priority in {"low", "normal", "high"} else "normal",
    )
    db.session.add(row)
    db.session.commit()
    return row.to_dict()


def get_user_tasks(user_id, include_completed=True, limit=200):
    q = Task.query.filter_by(user_id=user_id)
    if not include_completed:
        q = q.filter(Task.status != "completed")
    rows = q.order_by(Task.created_at.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


def mark_task_completed(task_id, user_id):
    row = Task.query.filter_by(id=task_id, user_id=user_id).first()
    if not row:
        return None
    row.status = "completed"
    db.session.commit()
    return row.to_dict()


def get_task_metrics(user_id):
    total = Task.query.filter_by(user_id=user_id).count()
    completed = Task.query.filter_by(user_id=user_id, status="completed").count()
    pending = Task.query.filter_by(user_id=user_id, status="pending").count()
    overdue = (
        Task.query.filter(
            Task.user_id == user_id,
            Task.status == "pending",
            Task.due_at.isnot(None),
            Task.due_at < datetime.utcnow(),
        )
        .count()
    )
    return {
        "total": total,
        "completed": completed,
        "pending": pending,
        "overdue": overdue,
    }
