import os
import json
import numpy as np
import joblib
from sklearn.svm import SVC
from utils.ai_service_unified import ai_service
from sklearn.preprocessing import LabelEncoder

MODEL_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(MODEL_DIR, "intent_model_v2.joblib")
ENCODER_PATH = os.path.join(MODEL_DIR, "label_encoder.joblib")

# ── Comprehensive training data aligned with Auralis SRS ────────────────────
TRAINING_DATA = [
    # ─ schedule_meeting ─────────────────────────────────────────────────────
    ("schedule a meeting with marketing tomorrow", "schedule_meeting"),
    ("set up a call with John at 3pm", "schedule_meeting"),
    ("book a 30 minute slot", "schedule_meeting"),
    ("interview tomorrow at 10am", "schedule_meeting"),
    ("arrange a team standup for Monday morning", "schedule_meeting"),
    ("create a weekly sync with the product team", "schedule_meeting"),
    ("set up a one-on-one with my manager", "schedule_meeting"),
    ("add a project kickoff call to my calendar", "schedule_meeting"),
    ("plan a catch-up with the sales team", "schedule_meeting"),
    ("book a brainstorming session for Friday", "schedule_meeting"),

    # ─ cancel_meeting ────────────────────────────────────────────────────────
    ("cancel my next meeting", "cancel_meeting"),
    ("delete the 3pm call", "cancel_meeting"),
    ("stop the sync meeting", "cancel_meeting"),
    ("remove my afternoon appointment", "cancel_meeting"),
    ("drop the Monday standup", "cancel_meeting"),
    ("kill the upcoming review session", "cancel_meeting"),
    ("I don't want to attend that call anymore", "cancel_meeting"),
    ("please cancel the meeting with Sarah", "cancel_meeting"),

    # ─ reschedule_meeting ────────────────────────────────────────────────────
    ("reschedule my 3pm call to 4pm", "reschedule_meeting"),
    ("move the marketing sync to Friday", "reschedule_meeting"),
    ("change the time of my interview", "reschedule_meeting"),
    ("shift my meeting with Sarah", "reschedule_meeting"),
    ("push the standup to tomorrow", "reschedule_meeting"),
    ("move my 10am meeting by an hour", "reschedule_meeting"),
    ("I need to change the client call time", "reschedule_meeting"),
    ("postpone the project review", "reschedule_meeting"),

    # ─ draft_email ───────────────────────────────────────────────────────────
    ("draft an email to Sarah saying thanks", "draft_email"),
    ("write a reply to the last email", "draft_email"),
    ("prepare a follow up email", "draft_email"),
    ("compose a message to management", "draft_email"),
    ("write a professional email declining the offer", "draft_email"),
    ("help me write a cold outreach email", "draft_email"),
    ("draft a meeting invite for the client", "draft_email"),
    ("compose an apology email to the team", "draft_email"),
    ("write a thank you note to the investors", "draft_email"),
    ("help me respond to this email professionally", "draft_email"),

    # ─ send_email ────────────────────────────────────────────────────────────
    ("send the email to John", "send_email"),
    ("dispatch the message", "send_email"),
    ("mail the report to the client", "send_email"),
    ("push that email out", "send_email"),
    ("go ahead and send it", "send_email"),
    ("deliver the message now", "send_email"),
    ("confirm and send the email draft", "send_email"),

    # ─ create_task ───────────────────────────────────────────────────────────
    ("create a task to buy milk", "create_task"),
    ("add task finish report", "create_task"),
    ("I need to complete the slides", "create_task"),
    ("new item: update website", "create_task"),
    ("add a to-do item for the proposal", "create_task"),
    ("make a note to follow up with the vendor", "create_task"),
    ("I have to review the contract by Friday", "create_task"),
    ("put submit the report on my task list", "create_task"),
    ("create a checklist item for the launch", "create_task"),
    ("track my progress on the sales deck", "create_task"),

    # ─ set_reminder ──────────────────────────────────────────────────────────
    ("remind me to call Mom", "set_reminder"),
    ("set a reminder for the deadline", "set_reminder"),
    ("alert me at 5pm about the gym", "set_reminder"),
    ("notify me to take medicine", "set_reminder"),
    ("ping me before the board meeting", "set_reminder"),
    ("don't let me forget to submit the report", "set_reminder"),
    ("remind me in 30 minutes to take a break", "set_reminder"),
    ("set an alarm for 9am tomorrow", "set_reminder"),
    ("alert me when the meeting is about to start", "set_reminder"),

    # ─ show_schedule ─────────────────────────────────────────────────────────
    ("what's on my schedule today", "show_schedule"),
    ("do I have any meetings right now", "show_schedule"),
    ("show my agenda", "show_schedule"),
    ("what is my calendar looking like", "show_schedule"),
    ("give me today's agenda", "show_schedule"),
    ("what are my upcoming meetings", "show_schedule"),
    ("am I free tomorrow morning", "show_schedule"),
    ("show me my weekly schedule", "show_schedule"),
    ("list all my appointments this week", "show_schedule"),
    ("when is my next call", "show_schedule"),

    # ─ daily_briefing ────────────────────────────────────────────────────────
    ("give me my daily briefing", "daily_briefing"),
    ("what should I focus on today", "daily_briefing"),
    ("morning summary please", "daily_briefing"),
    ("give me a plan for the day", "daily_briefing"),
    ("what's my digest for today", "daily_briefing"),
    ("summarize my day ahead", "daily_briefing"),
    ("what's happening today", "daily_briefing"),
    ("brief me on today's priorities", "daily_briefing"),
    ("what's on my radar today", "daily_briefing"),
    ("Auralis give me the morning rundown", "daily_briefing"),
    ("what do I have going on", "daily_briefing"),

    # ─ sync_email ────────────────────────────────────────────────────────────
    ("sync my inbox", "sync_email"),
    ("check my mail", "sync_email"),
    ("fetch new messages", "sync_email"),
    ("sync my inbox and find tasks for today", "sync_email"),
    ("show me unread emails", "sync_email"),
    ("pull in my latest emails", "sync_email"),
    ("hii give me all the unreaded mails", "sync_email"),
    ("load my recent messages", "sync_email"),
    ("get my email updates", "sync_email"),
    ("check if I have new mail", "sync_email"),
    ("refresh my inbox", "sync_email"),

    # ─ digital_twin / show_insights ──────────────────────────────────────────
    ("what has my digital twin learned about me", "show_insights"),
    ("show me my behavior patterns", "show_insights"),
    ("what patterns have you detected in my work", "show_insights"),
    ("tell me about my productivity habits", "show_insights"),
    ("show me my habit analysis", "show_insights"),
    ("what does Auralis know about my preferences", "show_insights"),
    ("analyze my work patterns", "show_insights"),
    ("give me my digital twin insights", "show_insights"),
    ("what are my peak productivity hours", "show_insights"),
    ("show my efficiency report", "show_insights"),

    # ─ proxy_meeting (expanded to fix confusion) ──────────────────────────────
    ("attend the meeting on my behalf", "proxy_meeting"),
    ("join the call for me", "proxy_meeting"),
    ("send AI to the standup", "proxy_meeting"),
    ("let Auralis represent me in the meeting", "proxy_meeting"),
    ("proxy that call", "proxy_meeting"),
    ("I can't make it, have the AI attend", "proxy_meeting"),
    ("use my digital twin for the conference call", "proxy_meeting"),
    ("can you join the meeting instead of me", "proxy_meeting"),
    ("I'm busy, have Auralis sit in", "proxy_meeting"),
    ("go to that call on my behalf", "proxy_meeting"),
    ("attend the board meeting for me", "proxy_meeting"),
    ("Auralis please represent me in today's standup", "proxy_meeting"),

    # ─ complex_query ─────────────────────────────────────────────────────────
    ("what is Auralis", "complex_query"),
    ("how does the digital twin work", "complex_query"),
    ("what can you do for me", "complex_query"),
    ("explain your features", "complex_query"),
    ("how do I use Auralis", "complex_query"),
    ("what is the status of the project", "complex_query"),
    ("help me brainstorm ideas for the pitch", "complex_query"),
    ("translate this text to French", "complex_query"),
    ("summarize this document", "complex_query"),
    ("who is the CEO of Apple", "complex_query"),
    ("hello", "complex_query"),
    ("hi Auralis", "complex_query"),
    ("what's up", "complex_query"),
    ("help me", "complex_query"),
    ("who are you", "complex_query"),

    # ─ extra edge cases from testing ─────────────────────────────────────────
    # Short send_email
    ("send it", "send_email"),
    ("fire it off", "send_email"),
    ("ok send", "send_email"),
    # Short daily_briefing
    ("brief me", "daily_briefing"),
    ("start my day", "daily_briefing"),
    ("today's overview", "daily_briefing"),
    # Short sync_email
    ("sync inbox", "sync_email"),
    ("check mail", "sync_email"),
    ("new emails", "sync_email"),
    # Short show_schedule
    ("show schedule", "show_schedule"),
    ("my agenda", "show_schedule"),
    ("calendar", "show_schedule"),
    # Short create_task
    ("new task", "create_task"),
    ("add todo", "create_task"),
    # Short set_reminder
    ("set reminder", "set_reminder"),
    ("remind me", "set_reminder"),
    # Short schedule_meeting
    ("schedule call", "schedule_meeting"),
    ("book meeting", "schedule_meeting"),
    # Short cancel
    ("cancel it", "cancel_meeting"),
    ("drop the meeting", "cancel_meeting"),
]


class IntentClassifier:
    def __init__(self):
        self.encoder = LabelEncoder()
        self.clf = None
        self._load_or_train()

    def _load_or_train(self):
        if os.path.exists(MODEL_PATH) and os.path.exists(ENCODER_PATH):
            try:
                self.clf = joblib.load(MODEL_PATH)
                self.encoder = joblib.load(ENCODER_PATH)
                print("[IntentClassifier] Model and Encoder loaded.")
                return
            except Exception as e:
                print(f"Failed to load intent model: {e}")


        try:
            # Train a new one
            print("[IntentClassifier] Training new Intent Classifier with Gemini Embeddings...")
            texts, labels = zip(*TRAINING_DATA)
            
            # Encode labels
            y = self.encoder.fit_transform(labels)
            
            # Generate embeddings via Gemini API
            X = []
            failure_count = 0
            for t in texts:
                emb = ai_service.get_embeddings(t)
                if emb:
                    X.append(emb)
                else:
                    failure_count += 1
                    if failure_count <= 3:
                        print(f"[IntentClassifier] Warning: Could not get embedding for text: {t}")
                    if failure_count == 4:
                        print("[IntentClassifier] Error: Too many embedding failures. Aborting training.")
                        break
            
            if not X or len(X) < len(texts) / 2:
                print("[IntentClassifier] Status: Insufficient embeddings for training. Falling back to LLM.")
                return

            # Train SVC (Probability=True to get confidence scores)
            self.clf = SVC(kernel='linear', probability=True, random_state=42)
            self.clf.fit(X, y)
            
            self.save_model()
        except Exception as e:
            print(f"[IntentClassifier] Training failed: {e}")
            self.clf = None

    def save_model(self):
        if self.clf:
            joblib.dump(self.clf, MODEL_PATH)
            joblib.dump(self.encoder, ENCODER_PATH)
            print("[IntentClassifier] Model saved successfully.")

    def predict_intent(self, text):
        if not text or len(text.strip()) < 3:
            return "unknown"
        
        try:
            # Generate embedding for prediction via Gemini API
            emb = ai_service.get_embeddings(text)
            if not emb:
                return self._zero_shot_fallback(text)
            
            if self.clf is None:
                print("[IntentClassifier] Warning: Model is not loaded. Using fallback.")
                return self._zero_shot_fallback(text)

            embedding = [emb]
            
            # Predict probability
            probs = self.clf.predict_proba(embedding)[0]
            max_prob = max(probs)
            
            print(f"[IntentClassifier] Prediction {text[:20]}... confidence: {max_prob:.2f}")

            # Confidence threshold
            if max_prob < 0.45:
                return self._zero_shot_fallback(text)
                
            class_idx = probs.argmax()
            intent = self.encoder.inverse_transform([class_idx])[0]
            return intent
        except Exception as e:
            print(f"[IntentClassifier] Prediction error: {e}")
            return self._zero_shot_fallback(text)

    def _zero_shot_fallback(self, text):
        """Zero-shot intent classification via LLM for high reliability."""
        print(f"[IntentClassifier] Falling back to Zero-Shot LLM for: {text[:30]}...")
        valid_intents = [
            'schedule_meeting', 'cancel_meeting', 'reschedule_meeting',
            'draft_email', 'send_email', 'create_task', 'set_reminder',
            'show_schedule', 'daily_briefing', 'sync_email',
            'show_insights', 'proxy_meeting', 'complex_query'
        ]
        prompt = (
            "Classify the user's intent from this list:\n"
            f"Intents: {', '.join(valid_intents)}\n"
            f'User Query: "{text}"\n'
            "Return ONLY the intent name. If unsure, return \'complex_query\'."
        )
        response = ai_service.generate_content(prompt, model='gemini-1.5-flash')
        if response and response.strip() in valid_intents:
            return response.strip()
        return "complex_query"

    def retrain(self):
        """Force retrain the classifier with current TRAINING_DATA."""
        import os as _os
        for p in [MODEL_PATH, ENCODER_PATH]:
            if _os.path.exists(p):
                _os.remove(p)
        self._load_or_train()
        return bool(self.clf)

# Singleton instance
intent_engine = IntentClassifier()
