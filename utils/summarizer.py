import os
from google.genai import Client

def summarize_text(text):
    """
    Analyzes meeting transcript and generates a summary using Google Gemini.
    """
    if not text:
        return "No transcript data available to summarize."
        
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Error: GEMINI_API_KEY not found in environment variables."

    try:
        client = Client(api_key=api_key)
        
        prompt = f"""
        You are an expert meeting assistant. Summarize the following meeting transcript.
        
        Transcript:
        {text}
        
        Please provide a comprehensive meeting report in EXACTLY this Markdown format:

        # Meeting Technical Report
        
        ## 🎯 Executive Overview
        [A high-level 2-3 sentence summary of the meeting's purpose and outcome]
        
        ## 🛠️ Key Discussion Points
        - **Topic A**: [Summary of discussion]
        - **Topic B**: [Summary of discussion]
        
        ## ✅ Important Decisions
        - [Decision 1]
        - [Decision 2]
        
        ## 📋 Action Items
        - [ ] **Assignee**: [Task description]
        - [ ] **Assignee**: [Task description]
        
        ## 📊 Sentiment & Engagement
        [Brief note on the meeting tone and participant engagement]
        """
        
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Gemini Summarization Error: {e}")
        return f"Error generating summary: {str(e)}"
