import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.vector_store import vector_store

def test_vector_store():
    print("Testing Vector Store...")
    
    # 1. Add Data
    meeting_id = "test_meeting_1"
    text = "The projected budget for Q4 is $50,000. Project Alpha requires immediate attention."
    metadata = {"title": "Q4 Planning"}
    
    print(f"Adding meeting {meeting_id}...")
    vector_store.add_meeting(meeting_id, text, metadata)
    
    # 2. Search
    print("Searching for 'budget'...")
    results = vector_store.search("What is the budget?")
    
    print(f"Found {len(results)} results.")
    for res in results:
        print(f"- {res['content']} (Score: {res['score']})")
        if "50,000" in res['content']:
            print("SUCCESS: Retrieved correct information.")
            return

    print("FAILURE: Did not retrieve correct information.")

if __name__ == "__main__":
    try:
        test_vector_store()
    except Exception as e:
        import traceback
        traceback.print_exc()
