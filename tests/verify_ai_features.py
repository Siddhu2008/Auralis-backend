import os
import sys

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Pre-monkey patch for eventlet DNS issues on Windows
import eventlet
eventlet.monkey_patch()
os.environ['EVENTLET_NO_GREENDNS'] = 'yes'

from dotenv import load_dotenv
load_dotenv()

from utils.summarizer import summarize_text
from utils.ai_response import generate_answer, generate_proxy_response

def verify_summarization():
    print("\n--- Verifying Summarization ---")
    transcript = """
    Host: Welcome everyone to the Q3 Planning meeting.
    Alice: I've updated the budget spreadsheets. We have $50k for marketing.
    Bob: Great. I'll start the campaign next week.
    Host: Decisions made: Marketing budget is $50k. Action items: Bob to start campaign.
    """
    summary = summarize_text(transcript)
    print("AI Summary Output:")
    print(summary)
    return "# Meeting Technical Report" in summary

def verify_proxy():
    print("\n--- Verifying Proxy Response ---")
    user_name = "Alice (Marketing Head)"
    user_profile = "Alice is professional, focused on ROI, and protective of the marketing budget."
    last_messages = "Host: We might need to redirect $10k from marketing to R&D. What do you think, Alice?"
    transcript = "..."
    
    response = generate_proxy_response(user_name, user_profile, last_messages, transcript)
    print(f"Alice's Proxy Response: {response}")
    return response is not None and "NO_RESPONSE_NEEDED" not in response

if __name__ == "__main__":
    s_ok = verify_summarization()
    p_ok = verify_proxy()
    
    print("\n--- Final Results ---")
    print(f"Summarization: {'PASS' if s_ok else 'FAIL'}")
    print(f"Proxy Response: {'PASS' if p_ok else 'FAIL'}")
    
    if s_ok and p_ok:
        sys.exit(0)
    else:
        sys.exit(1)
