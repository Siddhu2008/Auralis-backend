import os
from google.genai import Client

def get_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    return Client(api_key=api_key)

def generate_answer(context_chunks, question):
    """
    Generates an answer using Google Gemini based on the provided context.
    """
    client = get_client()
    if not client:
        return "Error: GEMINI_API_KEY not found in environment variables."

    context_text = "\n\n".join([chunk['content'] for chunk in context_chunks])
    
    prompt = f"""
    You are 'Auralis AI', an intelligent assistant for the Auralis platform.
    
    GUIDELINES:
    1. If the user is just saying hello or general chat, respond naturally and professionally.
    2. If the user asks a question about meetings, use the provided context below.
    3. If the answer is clearly requested from meetings but NOT in the context, say "I don't have that specific information in my meeting memory yet."
    
    Context:
    {context_text}
    
    Question: {question}
    
    Answer:
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        # Fallback for testing
        return "[Mock Answer] Based on the context, the budget is $50,000. (Generated because API call failed)."

def generate_avatar_chat(message, history=[], transcript=""):
    """
    Generates a response for the AI Avatar during a live meeting.
    """
    client = get_client()
    if not client:
        return "I'm here, but I need my API key to talk! Please check the backend settings."

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
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Avatar Gemini Error: {e}")
        return "I'm having a bit of trouble connecting to my brain right now, but I'm still listening!"

def generate_proxy_response(user_name, user_profile, last_messages, transcript):
    """
    Generates a response on behalf of an absent or proxy-enabled user.
    """
    client = get_client()
    if not client:
        return None

    prompt = f"""
    You are acting as a digital proxy for '{user_name}' in a live meeting.
    USER PROFILE CONTEXT: {user_profile or 'A professional participant.'}
    
    MEETING TRANSCRIPT SO FAR:
    {transcript[-3000:] if transcript else 'No transcript yet.'}
    
    LAST FEW MESSAGES:
    {last_messages}
    
    Based on the discussion, should you (as {user_name}) say something? 
    If yes, provide a concise, natural response that aligns with {user_name}'s perspective.
    If no response is necessary at this moment, return exactly the string: "NO_RESPONSE_NEEDED"
    
    STRICT RULE: Do not say 'As an AI proxy'. Speak naturally as {user_name}.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt
        )
        text = response.text.strip()
        if "NO_RESPONSE_NEEDED" in text:
            return None
        return text
    except Exception as e:
        print(f"Proxy Gemini Error: {e}")
        return None
