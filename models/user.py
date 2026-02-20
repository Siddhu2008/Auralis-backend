from database import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    profile_image = db.Column(db.String(500), nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    provider = db.Column(db.String(20), default='email') # 'email' or 'google'
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    meetings = db.relationship('Meeting', backref='host', lazy=True)
    schedules = db.relationship('Schedule', backref='user', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'google_id': self.google_id,
            'profile_image': self.profile_image,
            'provider': self.provider,
            'role': self.role,
            'created_at': self.created_at.isoformat()
        }

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def verify_password(self, raw_password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

def create_user(email, name, google_id=None, profile_image=None, provider='email'):
    user = User(email=email, name=name, google_id=google_id, profile_image=profile_image, provider=provider)
    db.session.add(user)
    db.session.commit()
    from models.user_settings import create_default_settings_for_user
    create_default_settings_for_user(user.id)
    return user.to_dict()

def find_user_by_email(email):
    user = User.query.filter_by(email=email).first()
    return user.to_dict() if user else None

def find_user_by_google_id(google_id):
    user = User.query.filter_by(google_id=google_id).first()
    return user.to_dict() if user else None

def find_user_by_id(user_id):
    user = User.query.get(user_id)
    return user.to_dict() if user else None
