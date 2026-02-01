import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from backend.utils.summarizer import summarize_text
    print("Successfully imported summarize_text")
except ImportError as e:
    print(f"Failed to import summarize_text: {e}")

try:
    from backend.utils.transcriber import transcribe_audio
    print("Successfully imported transcribe_audio")
except ImportError as e:
    print(f"Failed to import transcribe_audio: {e}")

try:
    from backend.socket_events import register_socket_events
    print("Successfully imported register_socket_events")
except ImportError as e:
    print(f"Failed to import register_socket_events: {e}")
