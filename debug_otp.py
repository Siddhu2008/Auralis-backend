import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

from app import app
import json

client = app.test_client()

print("Testing /api/auth/send-otp...")
try:
    with app.app_context():
        response = client.post('/api/auth/send-otp', 
                              data=json.dumps({'email': 'test@example.com'}),
                              content_type='application/json')
        print(f"Status: {response.status_code}")
        print(f"Data: {response.get_data(as_text=True)}")
except Exception as e:
    import traceback
    print(f"Crash during request: {e}")
    print(traceback.format_exc())
