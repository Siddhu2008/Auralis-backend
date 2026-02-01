import requests
import json
import time

BASE_URL = "http://127.0.0.1:5000/api"

def test_health():
    print("Testing /health...")
    try:
        res = requests.get(f"{BASE_URL}/health")
        print(f"Status: {res.status_code}")
        print(f"Response: {res.json()}")
        if res.status_code == 200:
            print("PASS: Health check passed.")
        else:
            print("FAIL: Health check failed.")
    except Exception as e:
        print(f"FAIL: Connection error: {e}")

def test_ask_ai():
    print("\nTesting /ai/ask...")
    # Requires vector store to have data. 
    # Since we are using native store on disk (vector_store.json), 
    # it likely persists if we ran test_vector.py previously.
    
    payload = {"question": "What is the budget?"}
    headers = {"Content-Type": "application/json"}
    
    try:
        res = requests.post(f"{BASE_URL}/ai/ask", json=payload, headers=headers)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
        
        if res.status_code == 200:
            data = res.json()
            if "answer" in data:
                print("PASS: AI Response received.")
                print(f"Answer: {data['answer']}")
                print(f"Sources: {len(data.get('sources', []))}")
            else:
                print("FAIL: No answer in response.")
        else:
            print(f"FAIL: API Error {res.status_code}")
    except Exception as e:
        print(f"FAIL: Connection error: {e}")

if __name__ == "__main__":
    # Wait a sec for server to be fully ready
    time.sleep(2)
    test_health()
    test_ask_ai()
