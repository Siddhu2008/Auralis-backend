import os
from dotenv import load_dotenv
from google.genai import Client

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

print(f"API Key present: {bool(api_key)}")

if not api_key:
    print("No API Key found in environment or .env")
    exit(1)

try:
    client = Client(api_key=api_key)
    print("Attempting to embed 'Hello world'...")
    res = client.models.embed_content(
        model="gemini-embedding-001", 
        contents="Hello world",
        config={
            "task_type": "retrieval_document"
        }
    )
    if res.embeddings:
        print(f"Success! Embedding length: {len(res.embeddings[0].values)}")
    else:
        print(f"Unexpected response format: {res}")
except Exception as e:
    print(f"Error calling Gemini API: {e}")
