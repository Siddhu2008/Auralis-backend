import os
import google.generativeai as genai

def generate_answer(context_chunks, question):
    """
    Generates an answer using Google Gemini based on the provided context.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Error: GEMINI_API_KEY not found in environment variables."

    genai.configure(api_key=api_key)
    
    # Construct prompt
    context_text = "\n\n".join([chunk['content'] for chunk in context_chunks])
    
    prompt = f"""
    You are an intelligent assistant for the Auralis meeting platform.
    Answer the user's question based strictly on the provided meeting context below.
    If the answer is not in the context, say "I don't have enough information from the meetings to answer that."
    
    Context:
    {context_text}
    
    Question: {question}
    
    Answer:
    """
    
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        # Fallback for testing
        return "[Mock Answer] Based on the context, the budget is $50,000. (Generated because API call failed)."

def generate_avatar_chat(message, history=[], transcript=""):
    """
    Generates a response for the AI Avatar during a live meeting.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "I'm here, but I need my API key to talk! Please check the backend settings."

    genai.configure(api_key=api_key)
    
    prompt = f"""
    You are 'Auralis AI', a helpful digital participant in a live video meeting.
    Your tone is professional, concise, and collaborative.
    You assist with taking notes, answering questions, and providing insights.
    
    Meeting Context so far:
    {transcript[-2000:] if transcript else 'No transcript yet.'}
    
    Last Message: {message}
    Conversation Context: {history[-5:] if history else 'None'}
    
    Response (concise, do not repeat the transcript):
    """
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Avatar Gemini Error: {e}")
        return "I'm having a bit of trouble connecting to my brain right now, but I'm still listening!"
