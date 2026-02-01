import os
import google.generativeai as genai

def transcribe_audio(file_path):
    """
    Transcribes audio using Google Gemini API.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Warning: No Gemini API Key. Returning mock transcript.")
        return {"text": "[Mock Transcript] Audio transcription unavailable without API Key."}

    genai.configure(api_key=api_key)
    
    try:
        # gemini-1.5-flash is good for multimodal (audio)
        model = genai.GenerativeModel('gemini-flash-latest')
        
        # Upload the file
        # Note: For production, we should handle file upload/lifecycle properly.
        # For this MVP, we assume the file is small enough or we use the File API.
        
        # Using the File API for audio
        audio_file = genai.upload_file(path=file_path)
        
        prompt = "Transcribe this audio file accurately."
        response = model.generate_content([prompt, audio_file])
        
        # Cleanup
        # genai.delete_file(audio_file.name) # clean up if needed immediately
        
        return {"text": response.text}
    except Exception as e:
        print(f"Gemini Transcription Error: {e}")
        # Fallback for testing if API fails (e.g. quota)
        return {"text": f"[Error] Could not transcribe: {str(e)}"}

