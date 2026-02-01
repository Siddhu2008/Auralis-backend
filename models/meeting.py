from pymongo import MongoClient
from datetime import datetime
from bson.objectid import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Client
try:
    # Try connecting with a short timeout to fail fast if offline
    client = MongoClient(os.getenv('MONGO_URI'), serverSelectionTimeoutMS=2000)
    client.server_info() # Trigger connection check
    print("Connected to MongoDB")
except Exception as e:
    print(f"MongoDB Connection Failed: {e}. Using Mock Database (In-Memory).")
    
    # Mock Classes for Offline Testing
    class MockCollection:
        def __init__(self): self.data = {}
        def insert_one(self, doc):
            from bson.objectid import ObjectId
            if '_id' not in doc: doc['_id'] = ObjectId()
            self.data[str(doc['_id'])] = doc
            class Res: inserted_id = doc['_id']
            return Res()
        def find(self, query):
            res = []
            for doc in self.data.values():
                match = True
                for k,v in query.items():
                    if k == '_id':
                        if str(doc.get('_id')) != str(v): match = False; break
                    elif doc.get(k) != v:
                        match = False; break
                if match: res.append(doc)
            class Cursor(list):
                def sort(self, *args): return self
                def limit(self, *args): return self
            return Cursor(res)
        def find_one(self, query):
            for doc in self.data.values():
                match = True
                for k,v in query.items():
                    if k == '_id':
                        if str(doc.get('_id')) != str(v): match = False; break
                    elif doc.get(k) != v:
                        match = False; break
                if match: return doc
            return None
        def delete_one(self, query):
            doc = self.find_one(query)
            if doc:
                del self.data[str(doc['_id'])]
                class Res: deleted_count = 1
                return Res()
            class Res: deleted_count = 0
            return Res()

    class MockDB:
        def __init__(self): self.collections = {}
        def __getitem__(self, key):
            if key not in self.collections: self.collections[key] = MockCollection()
            return self.collections[key]
        def __getattr__(self, key): return self[key]

    class MockClient:
        def __init__(self): self.dbs = {}
        def __getitem__(self, key):
            if key not in self.dbs: self.dbs[key] = MockDB()
            return self.dbs[key]
        def __getattr__(self, key): return self[key]
    
    client = MockClient()

db = client['auralis']
meetings_collection = db['meetings']

def create_meeting(user_id, room_id, title, transcript, summary, duration='N/A', participants_count=1):
    """Create a new meeting in the database"""
    meeting = {
        'user_id': user_id,
        'room_id': room_id,
        'title': title,
        'date': datetime.utcnow(),
        'transcript': transcript,
        'summary': summary,
        'duration': duration,
        'participants_count': participants_count
    }
    result = meetings_collection.insert_one(meeting)
    meeting['_id'] = str(result.inserted_id)
    meeting['date'] = meeting['date'].isoformat()
    return meeting

def get_user_meetings(user_id):
    """Get all meetings for a user"""
    meetings = list(meetings_collection.find({'user_id': user_id}).sort('date', -1))
    for meeting in meetings:
        meeting['_id'] = str(meeting['_id'])
        meeting['date'] = meeting['date'].isoformat()
    return meetings

def get_meeting_by_id(meeting_id, user_id):
    """Get a specific meeting by ID (with user verification)"""
    meeting = meetings_collection.find_one({
        '_id': ObjectId(meeting_id),
        'user_id': user_id
    })
    if meeting:
        meeting['_id'] = str(meeting['_id'])
        meeting['date'] = meeting['date'].isoformat()
    return meeting

def delete_meeting(meeting_id, user_id):
    """Delete a meeting (with user verification)"""
    result = meetings_collection.delete_one({
        '_id': ObjectId(meeting_id),
        'user_id': user_id
    })
    return result.deleted_count > 0
