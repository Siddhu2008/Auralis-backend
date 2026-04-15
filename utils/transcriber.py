import os
from google.genai import Client

def transcribe_audio(file_path):
    """
    Transcribes audio using Google Gemini API.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Warning: No Gemini API Key. Returning mock transcript.")
        return {"text": "[Mock Transcript] Audio transcription unavailable without API Key."}

    try:
        client = Client(api_key=api_key)
        
        # Upload the file
        # Note: In the new SDK, client.files.upload is the way to go.
        audio_file = client.files.upload(path=file_path)
        
        prompt = "Transcribe this audio file accurately."
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=[prompt, audio_file]
        )
        
        return {"text": response.text}
    except Exception as e:
        print(f"Gemini Transcription Error: {e}")
        # Fallback for testing if API fails (e.g. quota)
        return {"text": f"[Error] Could not transcribe: {str(e)}"}

