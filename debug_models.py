import os
import eventlet
eventlet.monkey_patch()
os.environ['EVENTLET_NO_GREENDNS'] = 'yes'

from google.genai import Client
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

print("Listing models...")
try:
    client = Client(api_key=api_key)
    for m in client.models.list():
        # Look for generation capabilities
        print(f"Name: {m.name}, Display: {m.display_name}")
except Exception as e:
    print(f"Error: {e}")
