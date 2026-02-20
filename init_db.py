from app import app
from database import db
import models.user
import models.meeting
import models.schedule
import models.notification
import models.reminder
import models.action_log
import models.user_preference
import models.user_settings

with app.app_context():
    print("Dropping existing database tables...")
    db.drop_all()
    print("Creating database tables...")
    db.create_all()
    print("Database tables created successfully.")
