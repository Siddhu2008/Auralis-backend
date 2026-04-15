from datetime import datetime
from database import db


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    source_type = db.Column(
        db.String(30), nullable=False, default="manual"
    )  # email/meeting/assistant/manual
    source_id = db.Column(db.String(64), nullable=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(
        db.String(20), nullable=False, default="pending"
    )  # pending/in-progress/completed/cancelled
    priority = db.Column(
        db.String(20), nullable=False, default="normal"
    )  # low/normal/high
    progress = db.Column(db.Integer, default=0)  # 0-100
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "title": self.title,
            "description": self.description,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "status": self.status,
            "priority": self.priority,
            "progress": self.progress,
            "created_at": self.created_at.isoformat() + "Z" if getattr(self, "created_at", None) else None,
            "updated_at": self.updated_at.isoformat() + "Z" if getattr(self, "updated_at", None) else None,
        }


def create_task(
    user_id,
    title,
    source_type="manual",
    source_id=None,
    due_at=None,
    priority="normal",
    description=None,
    progress=0,
):
    row = Task(
        user_id=user_id,
        title=title,
        description=description,
        source_type=source_type,
        source_id=str(source_id) if source_id is not None else None,
        due_at=due_at,
        priority=priority if priority in {"low", "normal", "high"} else "normal",
        progress=progress,
    )
    db.session.add(row)
    db.session.commit()

    # Centralized Notification
    try:
        from models.notification import create_notification
        from models.user_settings import get_or_create_user_settings

        settings = get_or_create_user_settings(user_id)
        if settings and settings.notifications_enabled:
            create_notification(user_id, f"New task created: {title}", type="task")
    except Exception as e:
        print(f"[create_task] Notification Error: {e}")

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


def update_task(task_id, user_id, **fields):
    row = Task.query.filter_by(id=task_id, user_id=user_id).first()
    if not row:
        return None
    allowed = {"title", "description", "due_at", "status", "priority", "progress"}
    for key, val in fields.items():
        if key in allowed and val is not None:
            setattr(row, key, val)
    db.session.commit()
    return row.to_dict()


def delete_task(task_id, user_id):
    row = Task.query.filter_by(id=task_id, user_id=user_id).first()
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def get_task_metrics(user_id):
    total = Task.query.filter_by(user_id=user_id).count()
    completed = Task.query.filter_by(user_id=user_id, status="completed").count()
    in_progress = Task.query.filter_by(
        user_id=user_id, status="in-progress"
    ).count()
    pending = Task.query.filter_by(user_id=user_id, status="pending").count()
    overdue = Task.query.filter(
        Task.user_id == user_id,
        Task.status != "completed",
        Task.due_at.isnot(None),
        Task.due_at < datetime.utcnow(),
    ).count()
    return {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "pending": pending,
        "overdue": overdue,
    }
