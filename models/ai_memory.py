from datetime import datetime
from database import db


class AIMemory(db.Model):
    __tablename__ = "ai_memory"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    embedding_vector = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "content": self.content,
            "embedding_vector": self.embedding_vector,
            "created_at": self.created_at.isoformat(),
        }


def add_memory(user_id, content, embedding_vector=None):
    row = AIMemory(user_id=user_id, content=content, embedding_vector=embedding_vector)
    db.session.add(row)
    db.session.commit()
    return row.to_dict()


def get_recent_memory(user_id, limit=20):
    rows = (
        AIMemory.query.filter_by(user_id=user_id)
        .order_by(AIMemory.created_at.desc())
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in rows]


def search_memory(user_id, query, limit=5):
    if not query:
        return []
    terms = [t.strip() for t in query.lower().split() if len(t.strip()) > 2][:5]
    if not terms:
        return get_recent_memory(user_id, limit=limit)

    q = AIMemory.query.filter_by(user_id=user_id)
    for term in terms:
        q = q.filter(AIMemory.content.ilike(f"%{term}%"))
    rows = q.order_by(AIMemory.created_at.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]
