import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

print(f"API Key present: {bool(api_key)}")

if not api_key:
    print("No API Key found in environment or .env")
    exit(1)

genai.configure(api_key=api_key)

try:
    print("Attempting to embed 'Hello world'...")
    res = genai.embed_content(
        model="models/embedding-001",
        content="Hello world",
        task_type="retrieval_document"
    )
    if 'embedding' in res:
        print(f"Success! Embedding length: {len(res['embedding'])}")
    else:
        print(f"Unexpected response format: {res}")
except Exception as e:
    print(f"Error calling Gemini API: {e}")
