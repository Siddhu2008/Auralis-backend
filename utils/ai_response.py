import os
from utils.ai_service_unified import ai_service

_AI_UNAVAILABLE_MSG = "I'm experiencing connectivity issues with my AI service. Please try again in a moment."

def generate_answer(context_chunks, question):
    """
    Generates an answer using Google Gemini based on the provided context.
    """
    context_text = "\n\n".join([chunk['content'] for chunk in context_chunks])
    
    # Build base prompt
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
    # Add a random suffix to encourage variability
    import random
    suffixes = ["", " Please elaborate.", " Could you provide more details?", " Let me think about that."]
    prompt += random.choice(suffixes)
    
    try:
        # Use our unified service which handles rotation and fallbacks automatically
        result = ai_service.generate_content(prompt, model='gemini-2.5-flash')
        return result or _AI_UNAVAILABLE_MSG
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return _AI_UNAVAILABLE_MSG

def generate_avatar_chat(message, history=[], transcript=""):
    """
    Generates a response for the AI Avatar during a live meeting.
    """
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
        # Use unified service
        res = ai_service.generate_content(prompt, model='gemini-2.5-flash')
        return res or "I'm listening and processing..."
    except Exception as e:
        print(f"Avatar Gemini Error: {e}")
        return "I'm having a bit of trouble connecting to my brain right now, but I'm still listening!"

def generate_proxy_response(user_name, user_profile, last_messages, transcript):
    """
    Generates a response on behalf of an absent or proxy-enabled user.
    """
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
        # Use unified service
        text = ai_service.generate_content(prompt, model='gemini-2.5-flash')
        if text and "NO_RESPONSE_NEEDED" in text:
            return None
        return text
    except Exception as e:
        print(f"Proxy Gemini Error: {e}")
        return None
