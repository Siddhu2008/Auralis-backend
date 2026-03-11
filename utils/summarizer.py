import os
from utils.ai_service_unified import ai_service


def summarize_text(text):
    """
    Analyzes meeting transcript and generates a summary using the unified AI service.
    """
    if not text:
        return "No transcript data available to summarize."

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

    try:
        result = ai_service.generate_content(prompt, model='gemini-2.5-flash')
        if result:
            return result
        return "Summary generation temporarily unavailable. Please try again."
    except Exception as e:
        print(f"Summarization Error: {e}")
        return f"Error generating summary: {str(e)}"
