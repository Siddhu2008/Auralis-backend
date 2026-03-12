# Mock shim for missing meeting_agent_bp

_active_agents = {}

def is_agent_active(room):
    return room in _active_agents

def feed_transcript_to_agent(room, text, user_id):
    # Mock behavior
    pass

def finalize_agent_meeting(room, user_id, title):
    # Mock report and qa pairs
    report = f"AI Summary for {title}: The participants discussed the project roadmap and identified key action items for the upcoming sprint."
    qa = [
        {"question": "What are the next steps?", "answer": "Finalize the backend API and start frontend integration."},
        {"question": "Who is responsible for the database?", "answer": "The engineering team will handle the schema migration."}
    ]
    return report, qa
