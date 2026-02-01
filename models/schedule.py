from pymongo import MongoClient
from datetime import datetime
from bson.objectid import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

# Use the same client setup as meeting.py
try:
    from models.meeting import client
except ImportError:
    # Fallback if called directly or meeting.py not available
    client = MongoClient(os.getenv('MONGO_URI'), serverSelectionTimeoutMS=2000)

db = client['auralis']
schedules_collection = db['scheduled_meetings']

def create_schedule(user_id, title, start_time, participants=None):
    """Schedule a new meeting"""
    schedule = {
        'user_id': user_id,
        'title': title,
        'start_time': start_time, # ISO string from frontend
        'participants': participants or [],
        'created_at': datetime.utcnow(),
        'status': 'upcoming'
    }
    result = schedules_collection.insert_one(schedule)
    schedule['_id'] = str(result.inserted_id)
    return schedule

def get_user_schedules(user_id):
    """Get all scheduled meetings for a user"""
    schedules = list(schedules_collection.find({'user_id': user_id, 'status': 'upcoming'}).sort('start_time', 1))
    for s in schedules:
        s['_id'] = str(s['_id'])
        if isinstance(s.get('created_at'), datetime):
            s['created_at'] = s['created_at'].isoformat()
    return schedules

def delete_schedule(schedule_id, user_id):
    """Cancel a scheduled meeting"""
    result = schedules_collection.delete_one({
        '_id': ObjectId(schedule_id),
        'user_id': user_id
    })
    return result.deleted_count > 0
