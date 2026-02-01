import os
import google.generativeai as genai

def summarize_text(text):
    """
    Analyzes meeting transcript and generates a summary using Google Gemini.
    """
    if not text:
        return "No transcript data available to summarize."
        
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Error: GEMINI_API_KEY not found in environment variables."

    genai.configure(api_key=api_key)
    
    prompt = f"""
    You are an expert meeting assistant. Summarize the following meeting transcript.
    
    Transcript:
    {text}
    
    Please provide the summary in the following Markdown format:
    ### AI Meeting Insights
    **Overview**: [Brief summary of the meeting]
    
    **Key Points**:
    - [Point 1]
    - [Point 2]
    
    **Action Items**:
    - [ ] [Action Item 1]
    - [ ] [Action Item 2]
    """
    
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini Summarization Error: {e}")
        return f"Error generating summary: {str(e)}"
