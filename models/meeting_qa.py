from database import db
from datetime import datetime


class MeetingQA(db.Model):
    """Stores question-answer pairs detected during a live meeting by the AI agent."""
    __tablename__ = 'meeting_qa'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(200), nullable=False, index=True)
    user_id = db.Column(db.String(200), nullable=False, index=True)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    speaker = db.Column(db.String(200), nullable=True)
    confidence = db.Column(db.Float, default=1.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'room_id': self.room_id,
            'user_id': self.user_id,
            'question': self.question,
            'answer': self.answer,
            'speaker': self.speaker,
            'confidence': self.confidence,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


def save_qa_pair(room_id, user_id, question, answer, speaker=None, confidence=1.0):
    qa = MeetingQA(
        room_id=room_id,
        user_id=user_id,
        question=question,
        answer=answer,
        speaker=speaker,
        confidence=confidence,
    )
    db.session.add(qa)
    db.session.commit()
    return qa.to_dict()


def get_room_qa(room_id):
    pairs = MeetingQA.query.filter_by(room_id=room_id).order_by(MeetingQA.timestamp).all()
    return [p.to_dict() for p in pairs]
