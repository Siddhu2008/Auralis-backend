import sys
import os
import uuid

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

def test_phase5():
    print("--- Starting Phase 5: Digital Twin Memory Verification ---")
    
    try:
        from backend.utils.vector_store import vector_store
        from backend.utils.ai_response import generate_answer
        
        # 1. Index Mock Data
        meeting_id = str(uuid.uuid4())
        mock_transcript = """
        The team decided to launch the product on Friday. 
        Marketing budget is set at $10k for the first week.
        The main concern is server scalability.
        """
        print(f"Indexing mock meeting {meeting_id}...")
        vector_store.add_meeting(meeting_id, mock_transcript, metadata={'title': 'Launch Sync'})
        
        # 2. Search
        query = "What is the marketing budget?"
        print(f"\nSearching for: '{query}'")
        results = vector_store.search(query)
        
        print("\nRetrieval Results:")
        for r in results:
            print(f"- {r['content'][:50]}... (Score: {r['score']})")
            
        if not results:
            print("FAILURE: No results found.")
            return

        # 3. Ask AI (Generate Answer)
        print("\nGenerating Answer with Gemini...")
        # Check API KEY first
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
             print("SKIPPING GENERATION: No API Key found.")
        else:
             answer = generate_answer(results, query)
             print(f"\nAI Answer:\n{answer}")
             
        print("\nPhase 5 Verified Successfully.")

    except Exception as e:
        print(f"\nCRITICAL FAILURE Phase 5: {e}")

if __name__ == "__main__":
    test_phase5()
