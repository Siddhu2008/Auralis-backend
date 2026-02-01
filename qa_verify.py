import requests
import json
import time

BASE_URL = "http://localhost:5000/api"

def test_health():
    print("Testing /health ...", end=" ")
    try:
        res = requests.get(f"{BASE_URL}/health")
        print("OK" if res.status_code == 200 else f"FAILED ({res.status_code})")
    except Exception as e:
        print(f"ERROR: {e}")

def test_schedules():
    print("Testing /schedules ...", end=" ")
    # Mock token for testing (since we have offline check)
    headers = {"Authorization": "Bearer mock_token"}
    try:
        # 1. Create
        data = {"title": "QA Verification Sync", "start_time": "2026-02-01T15:00:00"}
        res = requests.post(f"{BASE_URL}/schedules", json=data, headers=headers)
        if res.status_code != 201:
            print(f"POST FAILED ({res.status_code}): {res.text}")
            return
        
        # 2. Get
        res = requests.get(f"{BASE_URL}/schedules", headers=headers)
        if res.status_code == 200:
            print("OK")
        else:
            print(f"GET FAILED ({res.status_code})")
    except Exception as e:
        print(f"ERROR: {e}")

def test_notifications():
    print("Testing /notifications ...", end=" ")
    headers = {"Authorization": "Bearer mock_token"}
    try:
        res = requests.get(f"{BASE_URL}/notifications", headers=headers)
        print("OK" if res.status_code == 200 else f"FAILED ({res.status_code})")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    time.sleep(2) # Wait for server
    test_health()
    test_schedules()
    test_notifications()
