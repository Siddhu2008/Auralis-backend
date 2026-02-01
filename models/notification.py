from datetime import datetime
from bson.objectid import ObjectId
import os

try:
    from models.meeting import client
except ImportError:
    from pymongo import MongoClient
    client = MongoClient(os.getenv('MONGO_URI'), serverSelectionTimeoutMS=2000)

db = client['auralis']
notifications_collection = db['notifications']

def create_notification(user_id, message, type='info'):
    """Create a notification for a user"""
    notif = {
        'user_id': user_id,
        'message': message,
        'type': type, # 'info', 'success', 'warning', 'error'
        'created_at': datetime.utcnow(),
        'is_read': False
    }
    result = notifications_collection.insert_one(notif)
    notif['_id'] = str(result.inserted_id)
    return notif

def get_user_notifications(user_id, only_unread=True):
    """Get notifications for a user"""
    query = {'user_id': user_id}
    if only_unread:
        query['is_read'] = False
        
    notifs = list(notifications_collection.find(query).sort('created_at', -1).limit(20))
    for n in notifs:
        n['_id'] = str(n['_id'])
        if isinstance(n.get('created_at'), datetime):
            n['created_at'] = n['created_at'].isoformat()
    return notifs

def mark_as_read(notif_id, user_id):
    """Mark a notification as read"""
    result = notifications_collection.update_one(
        {'_id': ObjectId(notif_id), 'user_id': user_id},
        {'$set': {'is_read': True}}
    )
    return result.modified_count > 0
