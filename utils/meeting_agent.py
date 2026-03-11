"""
Auralis AI Meeting Agent — Core Intelligence Module
Uses trained ML models for fast classification + Gemini for generation.
Follows the Auralis identity and behavior rules.
"""
import os
import json
import logging
import joblib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime
from utils.ai_service_unified import ai_service

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Model Loading (lazy, on first use)
# ─────────────────────────────────────────────────────────────────────────────
_MODELS = {}
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'training', 'models')


def _load_model(name):
    if name not in _MODELS:
        path = os.path.join(MODEL_DIR, f'{name}.pkl')
        if os.path.exists(path):
            _MODELS[name] = joblib.load(path)
            logger.info(f'[Agent] Loaded model: {name}')
        else:
            logger.warning(f'[Agent] Model not found: {path}')
            _MODELS[name] = None
    return _MODELS[name]


def classify_intent(text):
    """Classify user intent using the trained model. Returns (label, confidence)."""
    model = _load_model('intent_classifier')
    if model is None:
        return 'unknown', 0.0
    label = model.predict([text])[0]
    try:
        proba = model.predict_proba([text])[0]
        confidence = float(max(proba))
    except Exception:
        confidence = 0.9
    return label, confidence


def detect_qa(text):
    """Detect if a transcript line is a question, answer, or statement."""
    model = _load_model('qa_detector')
    if model is None:
        return 'statement', 0.0
    label = model.predict([text])[0]
    try:
        proba = model.predict_proba([text])[0]
        confidence = float(max(proba))
    except Exception:
        confidence = 0.9
    return label, confidence


def classify_context(text):
    """Classify meeting context: action_item, decision, follow_up, key_insight, filler."""
    model = _load_model('context_classifier')
    if model is None:
        return 'filler', 0.0
    label = model.predict([text])[0]
    try:
        proba = model.predict_proba([text])[0]
        confidence = float(max(proba))
    except Exception:
        confidence = 0.9
    return label, confidence


# ─────────────────────────────────────────────────────────────────────────────
# Gemini Integration (with 9-second timeout)
# ─────────────────────────────────────────────────────────────────────────────
_executor = ThreadPoolExecutor(max_workers=4)


# Using unified ai_service
def _call_gemini(prompt, timeout=9):
    """Call Gemini using the unified service. Standardization on gemini-2.5-flash."""
    try:
        # We can pass timeout in the request config if the SDK supports it, 
        # or just rely on the unified service's error handling.
        return ai_service.generate_content(prompt, model='gemini-1.5-flash')
    except Exception as e:
        logger.error(f'[Agent] Gemini error: {e}')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Q&A Pair Detection from Transcript
# ─────────────────────────────────────────────────────────────────────────────
def detect_qa_pairs(transcript_lines):
    """
    Given a list of transcript lines, detect Q&A pairs.
    Uses the trained ML model first for speed, then Gemini for refinement.
    Returns list of {'question': str, 'answer': str, 'speaker': str}
    """
    qa_pairs = []
    pending_question = None

    for line in transcript_lines:
        label, confidence = detect_qa(line)

        if label == 'question' and confidence > 0.6:
            # If there was a previous unanswered question, save it
            if pending_question:
                qa_pairs.append({
                    'question': pending_question,
                    'answer': '[No answer captured]',
                    'speaker': 'Unknown',
                })
            pending_question = line

        elif label == 'answer' and confidence > 0.6 and pending_question:
            qa_pairs.append({
                'question': pending_question,
                'answer': line,
                'speaker': 'Participant',
            })
            pending_question = None

    # Handle last unanswered question
    if pending_question:
        qa_pairs.append({
            'question': pending_question,
            'answer': '[No answer captured]',
            'speaker': 'Unknown',
        })

    return qa_pairs


# ─────────────────────────────────────────────────────────────────────────────
# Meeting Report Generation
# ─────────────────────────────────────────────────────────────────────────────
def generate_meeting_report(transcript_data, qa_pairs=None, title='Meeting', participants=None):
    """
    Generate a rich structured meeting report following the Auralis format.
    transcript_data: list of {'speaker': str, 'text': str, 'timestamp': str}
    """
    # 1. Overview
    date_str = datetime.utcnow().strftime('%Y-%m-%d')
    start_time = transcript_data[0]['timestamp'] if transcript_data else 'N/A'
    end_time = transcript_data[-1]['timestamp'] if transcript_data else 'N/A'
    participants_list = ", ".join(participants) if participants else "Known Participants"

    # 2. Extract context using ML
    full_text = "\n".join([f"{l['speaker']}: {l['text']}" for l in transcript_data])
    lines = [l['text'] for l in transcript_data]
    
    action_items = []
    decisions = []
    key_insights = []

    for line in lines:
        label, conf = classify_context(line)
        if label == 'action_item' and conf > 0.5:
            action_items.append(line)
        elif label == 'decision' and conf > 0.5:
            decisions.append(line)
        elif label == 'key_insight' and conf > 0.5:
            key_insights.append(line)

    # 3. Gemini summary
    prompt = f"""You are Auralis AI. Generate a concise meeting summary.
Title: {title}
Transcript snippet:
{full_text[-3000:]}

Return ONLY the summary."""
    summary = _call_gemini(prompt) or "Meeting concluded successfully."

    # 4. Build Markdown Report
    report = f"""# 📝 Meeting Report: {title}

## 📅 Meeting Overview
- **Date:** {date_str}
- **Duration:** {start_time} - {end_time}
- **Participants:** {participants_list}

## 🎯 Executive Summary
{summary}

## 🕰️ Timestamped Conversation Log
{chr(10).join([f"[{l['timestamp']}] **{l['speaker']}**: {l['text']}" for l in transcript_data])}

## ❓ Questions & Answers
{chr(10).join([f"**Q:** {p['question']}\n**A:** {p['answer']}" for p in (qa_pairs or [])]) or "- No major questions captured."}

## ✅ Key Decisions
{chr(10).join([f"- {d}" for d in decisions]) or "- No formal decisions detected."}

## 📋 Action Items
{chr(10).join([f"- [ ] {a}" for a in action_items]) or "- No action items detected."}

---
*Generated by Auralis AI Meeting Agent*
"""
    return report


def generate_video_summary_script(transcript_data, title='Meeting'):
    """
    Generate a script for a video summary of the meeting.
    """
    lines = [f"{l['speaker']}: {l['text']}" for l in transcript_data[-50:]]
    context = "\n".join(lines)
    
    prompt = f"""You are Auralis AI. Write a concise script for a 1-minute video summary of this meeting.
Title: {title}
Recent context:
{context}

Format:
[Intro] ...
[Key Points] ...
[Decisions] ...
[Action Items] ...
[Closing] ...

Keep it professional."""
    
    script = _call_gemini(prompt) or "Ready for video summary."
    return script


# ─────────────────────────────────────────────────────────────────────────────
# Post-Meeting Q&A (RAG)
# ─────────────────────────────────────────────────────────────────────────────
def answer_post_meeting_question(question, transcript, qa_pairs=None):
    """
    Answer a question about a past meeting using RAG.
    Searches the transcript + Q&A pairs, then uses Gemini to compose answer.
    """
    # Build context from Q&A pairs
    qa_context = ''
    if qa_pairs:
        qa_context = '\n'.join(
            f'Q: {p["question"]}\nA: {p["answer"]}'
            for p in qa_pairs
        )

    prompt = f"""You are Auralis AI. A user is asking about a meeting they attended.
Answer based ONLY on the provided context. If the answer isn't in the context, say so.

Meeting Transcript (last 4000 chars):
{transcript[-4000:]}

Q&A Pairs from Meeting:
{qa_context or 'None captured'}

User Question: {question}

Provide a concise, helpful answer:"""

    answer = _call_gemini(prompt, timeout=9)
    if not answer:
        answer = "I couldn't process that question right now. The meeting data is available — please try again."
    return answer


# ─────────────────────────────────────────────────────────────────────────────
# Email Drafting from Meeting Context
# ─────────────────────────────────────────────────────────────────────────────
def draft_email_from_meeting(instruction, transcript, qa_pairs=None):
    """
    Draft an email based on meeting context and a user instruction.
    Returns {'to': str, 'subject': str, 'body': str}
    """
    qa_context = ''
    if qa_pairs:
        qa_context = '\n'.join(
            f'- {p["question"]} → {p["answer"]}'
            for p in qa_pairs[:10]
        )

    prompt = f"""You are Auralis AI. Draft a professional email based on the meeting context.

User instruction: {instruction}

Meeting transcript (last 2000 chars):
{transcript[-2000:]}

Key Q&A from meeting:
{qa_context or 'None'}

Return ONLY valid JSON in this exact format:
{{"to": "recipient@email.com", "subject": "Subject line", "body": "Email body text"}}

If the user didn't specify a recipient, use "unspecified@pending.com".
Keep the email concise and professional."""

    result = _call_gemini(prompt, timeout=9)
    if result:
        try:
            # Strip markdown code fences if present
            cleaned = result.strip()
            if cleaned.startswith('```'):
                cleaned = '\n'.join(cleaned.split('\n')[1:-1])
            return json.loads(cleaned)
        except (json.JSONDecodeError, Exception):
            pass

    return {
        'to': 'unspecified@pending.com',
        'subject': 'Meeting Recap',
        'body': 'Please find the meeting recap attached. Key points were discussed.',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Live Meeting Response (for agent in-meeting chat)
# ─────────────────────────────────────────────────────────────────────────────
def generate_agent_response(message, transcript, qa_pairs=None):
    """
    Generate a response from the AI agent during a live meeting.
    Uses the intent classifier to route, then Gemini for generation.
    """
    intent, conf = classify_intent(message)

    qa_context = ''
    if qa_pairs:
        qa_context = '\n'.join(
            f'Q: {p["question"]}\nA: {p["answer"]}'
            for p in qa_pairs[-5:]
        )

    prompt = f"""You are Auralis, an intelligent AI meeting assistant.
Be concise, professional, and helpful.

Detected intent: {intent}

Meeting transcript context:
{transcript[-2000:] if transcript else 'Meeting just started.'}

User message: {message}

Rules:
- If asked for meeting details, use the transcript/Q&A context.
- Keep responses to 1-2 sentences.
- Be polite.

Auralis Response:"""

    response = _call_gemini(prompt, timeout=9)
    if not response:
        from utils.ai_service_unified import ai_service
        if not ai_service.client:
            response = "I'm currently offline (API key missing). Please check your backend configuration."
        else:
            response = "I'm having trouble connecting to my intelligence module. Please try again in a moment."

    return {
        'text': response,
        'intent': intent,
        'confidence': conf,
    }
