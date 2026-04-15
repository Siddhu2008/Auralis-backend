from database import db

class UserPreference(db.Model):
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    pref_key = db.Column(db.String(50), nullable=False) # e.g., 'frequent_contacts', 'preferred_time'
    pref_value = db.Column(db.JSON, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "pref_key": self.pref_key,
            "pref_value": self.pref_value
        }

def set_preference(user_id, key, value):
    pref = UserPreference.query.filter_by(user_id=user_id, pref_key=key).first()
    if pref:
        pref.pref_value = value
    else:
        pref = UserPreference(user_id=user_id, pref_key=key, pref_value=value)
        db.session.add(pref)
    db.session.commit()
    return pref.to_dict()

def get_preferences(user_id):
    prefs = UserPreference.query.filter_by(user_id=user_id).all()
    return {p.pref_key: p.pref_value for p in prefs}
