from datetime import datetime
from database import db


class Email(db.Model):
    __tablename__ = "emails"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=False)
    summary = db.Column(db.Text, nullable=True)
    recipient = db.Column(db.String(200), nullable=True)
    direction = db.Column(db.String(20), default="outgoing", nullable=False)  # outgoing/incoming/draft
    category = db.Column(db.String(20), default="normal", nullable=False)  # urgent/normal/spam
    approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "subject": self.subject,
            "body": self.body,
            "summary": self.summary,
            "recipient": self.recipient,
            "direction": self.direction,
            "category": self.category,
            "approved": self.approved,
            "created_at": self.created_at.isoformat(),
        }


def create_email_entry(
    user_id,
    subject,
    body,
    summary=None,
    recipient=None,
    direction="outgoing",
    category="normal",
    approved=False,
):
    row = Email(
        user_id=user_id,
        subject=subject,
        body=body,
        summary=summary,
        recipient=recipient,
        direction=direction,
        category=category if category in {"urgent", "normal", "spam"} else "normal",
        approved=approved,
    )
    db.session.add(row)
    db.session.commit()
    return row.to_dict()


def get_user_emails(user_id, limit=50):
    rows = (
        Email.query.filter_by(user_id=user_id)
        .order_by(Email.created_at.desc())
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in rows]


def get_email_metrics(user_id):
    total = Email.query.filter_by(user_id=user_id).count()
    urgent = Email.query.filter_by(user_id=user_id, category="urgent").count()
    outgoing = Email.query.filter_by(user_id=user_id, direction="outgoing").count()
    return {
        "total": total,
        "urgent": urgent,
        "outgoing": outgoing,
    }
