from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Client
try:
    client = MongoClient(os.getenv('MONGO_URI'), serverSelectionTimeoutMS=2000)
    client.server_info()
    print("Connected to MongoDB (User Model)")
except Exception:
    print("MongoDB Connection Failed (User Model). Using Mock Database.")
    from models.meeting import client # Reuse the mock client from meeting.py if possible or recreate

    class MockCollection:
        def __init__(self): self.data = {}
        def insert_one(self, doc):
            from bson.objectid import ObjectId
            if '_id' not in doc: doc['_id'] = ObjectId()
            self.data[str(doc['_id'])] = doc
            class Res: inserted_id = doc['_id']
            return Res()
        def find_one(self, query):
            from bson.objectid import ObjectId
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
users_collection = db['users']

def create_user(email, name, google_id=None):
    """Create a new user in the database"""
    user = {
        'email': email,
        'name': name,
        'google_id': google_id,
        'role': 'user', # Default role
        'created_at': datetime.utcnow()
    }
    result = users_collection.insert_one(user)
    user['_id'] = str(result.inserted_id)
    return user

def find_user_by_email(email):
    """Find user by email"""
    user = users_collection.find_one({'email': email})
    if user:
        user['_id'] = str(user['_id'])
    return user

def find_user_by_google_id(google_id):
    """Find user by Google ID"""
    user = users_collection.find_one({'google_id': google_id})
    if user:
        user['_id'] = str(user['_id'])
    return user

def find_user_by_id(user_id):
    """Find user by ID"""
    from bson.objectid import ObjectId
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if user:
        user['_id'] = str(user['_id'])
    return user
