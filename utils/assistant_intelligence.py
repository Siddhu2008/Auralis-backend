import json
import os
import re
from datetime import datetime, timedelta
from utils.ai_service_unified import ai_service

# Unified ai_service used


def categorize_email(subject, body):
    text = f"{subject} {body}".lower()
    spam_terms = ["lottery", "winner", "casino", "free money", "crypto doubling", "click here"]
    urgent_terms = ["urgent", "asap", "immediately", "deadline", "today", "blocking", "critical"]
    if any(t in text for t in spam_terms):
        return "spam"
    if any(t in text for t in urgent_terms):
        return "urgent"
    return "normal"


def extract_action_items(text):
    if not text:
        return []
    candidates = []
    for line in text.splitlines():
        line = line.strip(" -\t")
        if not line:
            continue
        if re.search(r"\b(todo|action|follow up|send|prepare|review|complete|reply)\b", line.lower()):
            candidates.append({"title": line, "due_date": None})
    return candidates[:10]


def ai_structured_chat(prompt, default_response):
    import time
    try:
        config = {"response_mime_type": "application/json", "max_output_tokens": 900}
        raw = ai_service.generate_content(prompt, model="gemini-2.5-flash", config=config)
        
        # If rate-limited, wait briefly and retry once
        if not raw:
            time.sleep(3)
            raw = ai_service.generate_content(prompt, model="gemini-2.5-flash", config=config)
        
        if not raw:
            return normalize_chat_payload({}, default_response)

        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif raw.startswith("```"):
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        data = json.loads(raw)
        return normalize_chat_payload(data, default_response)
    except Exception:
        return normalize_chat_payload({}, default_response)


def normalize_chat_payload(data, default_response="Done."):
    if not isinstance(data, dict):
        data = {}
    response = data.get("response")
    if not isinstance(response, str) or not response.strip():
        response = default_response
    action = data.get("action")
    if action not in {"schedule", "modify", "cancel", "email", "task", "sync", "set_pref", None}:
        action = None
    action_data = data.get("action_data")
    if not isinstance(action_data, dict):
        action_data = {}
    confidence = data.get("confidence", 0.75)
    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.75
    confidence = max(0.0, min(1.0, confidence))
    return {
        "response": response.strip(),
        "action": action,
        "action_data": action_data,
        "confidence": confidence,
        "generated_at": datetime.utcnow().isoformat(),
    }


def suggest_proactive_items(schedules, tasks, emails):
    suggestions = []
    if len(schedules) >= 3:
        suggestions.append("You have multiple meetings tomorrow. Generate briefing?")
    if any(t.get("status") == "pending" and t.get("priority") == "high" for t in tasks):
        suggestions.append("High-priority pending tasks detected. Want a focused plan?")
    if any(e.get("category") == "urgent" for e in emails):
        suggestions.append("Urgent emails are pending. Draft replies now?")
    return suggestions[:3]


def contextual_fallback_response(user_message, context):
    msg = (user_message or "").strip().lower()
    action_history = context.get("action_history", []) or []
    schedules = context.get("upcoming_schedules", []) or []
    meetings = context.get("recent_meeting_summaries", []) or []
    memory_hits = context.get("memory_hits", []) or []

    now = datetime.utcnow()
    yesterday_date = (now - timedelta(days=1)).date()

    if "yesterday" in msg:
        yesterday_actions = []
        for item in action_history:
            ts = item.get("timestamp")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.date() == yesterday_date:
                    yesterday_actions.append(item)
            except Exception:
                continue

        if not yesterday_actions:
            return {
                "response": "I could not find explicit logged actions from yesterday. You can ask me to summarize recent meetings or emails.",
                "action": None,
                "action_data": {},
                "confidence": 0.8,
            }

        action_counts = {}
        for item in yesterday_actions:
            t = item.get("action_type", "activity")
            action_counts[t] = action_counts.get(t, 0) + 1
        parts = [f"{k}: {v}" for k, v in sorted(action_counts.items())]
        return {
            "response": f"Yesterday you completed {len(yesterday_actions)} logged actions ({', '.join(parts)}).",
            "action": None,
            "action_data": {},
            "confidence": 0.85,
        }

    if "today" in msg and ("agenda" in msg or "plan" in msg):
        if not schedules:
            return {
                "response": "You do not have scheduled meetings today in the current data.",
                "action": None,
                "action_data": {},
                "confidence": 0.8,
            }
        titles = [s.get("title", "Meeting") for s in schedules[:3]]
        return {
            "response": f"Today you have {len(schedules)} scheduled meetings. Next items: {', '.join(titles)}.",
            "action": None,
            "action_data": {},
            "confidence": 0.8,
        }

    if "last week" in msg or "client call" in msg or "what did we decide" in msg:
        if meetings:
            snippets = []
            for m in meetings[:3]:
                title = m.get("title", "Meeting")
                summary = (m.get("summary") or "No summary").strip()
                snippets.append(f"{title}: {summary[:120]}")
            return {
                "response": "Recent meeting recap: " + " | ".join(snippets),
                "action": None,
                "action_data": {},
                "confidence": 0.78,
            }
        if memory_hits:
            first = memory_hits[0].get("content", "")
            return {
                "response": f"I found relevant memory: {first[:220]}",
                "action": None,
                "action_data": {},
                "confidence": 0.7,
            }

    # Final fallback - give a helpful professional response
    return {
        "response": "I'm ready to assist you. You can ask me to schedule a meeting, send an email, check your agenda, or help with tasks. What would you like to do?",
        "action": None,
        "action_data": {},
        "confidence": 0.5,
    }
