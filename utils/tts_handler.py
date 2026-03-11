"""
Text-to-Speech handler for the Auralis AI Meeting Agent.
Uses gTTS (free, no API key required) to produce a human-like voice.
Falls back silently if unavailable so the rest of the agent still works.
"""
import io
import base64
import logging

logger = logging.getLogger(__name__)


def text_to_speech_base64(text: str, lang: str = 'en') -> str | None:
    """
    Convert text to an MP3 audio clip and return it as a base64-encoded string.
    The frontend decodes this and plays it through the browser Audio API.

    Returns None if TTS is unavailable (missing dependency, empty text, etc.)
    """
    if not text or not text.strip():
        return None

    # Keep responses concise so TTS finishes quickly (≤10 s rule)
    max_chars = 600
    trimmed = text.strip()[:max_chars]
    if len(text.strip()) > max_chars:
        # End on a sentence boundary where possible
        last_period = trimmed.rfind('.')
        if last_period > 200:
            trimmed = trimmed[:last_period + 1]

    try:
        from gtts import gTTS  # type: ignore
        tts = gTTS(text=trimmed, lang=lang, slow=False)
        buffer = io.BytesIO()
        tts.write_to_fp(buffer)
        buffer.seek(0)
        encoded = base64.b64encode(buffer.read()).decode('utf-8')
        return encoded
    except ImportError:
        logger.warning('[TTS] gTTS not installed. Run: pip install gtts')
        return None
    except Exception as exc:
        logger.error(f'[TTS] Failed to generate audio: {exc}')
        return None
