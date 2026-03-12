import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
import joblib

MODEL_PATH = os.path.join(os.path.dirname(__file__), "intent_model.joblib")

# Baseline training data for the Digital Twin Intents
TRAINING_DATA = [
    # text, intent
    ("schedule a meeting with marketing tomorrow", "schedule_meeting"),
    ("set up a call with John at 3pm", "schedule_meeting"),
    ("book a 30 minute slot", "schedule_meeting"),
    
    ("draft an email to Sarah saying thanks", "draft_email"),
    ("write a reply to the last email", "draft_email"),
    ("send a quick note to the team", "draft_email"),
    
    ("cancel my next meeting", "cancel_meeting"),
    ("delete the 3pm call", "cancel_meeting"),
    
    ("remind me to buy milk tomorrow", "set_reminder"),
    ("add a task to finish the report by Friday", "set_reminder"),
    
    ("what's on my schedule today", "show_schedule"),
    ("do I have any meetings right now", "show_schedule"),
    ("show agenda", "show_schedule"),
    
    ("give me my daily briefing", "daily_briefing"),
    ("what should I focus on today", "daily_briefing"),
    ("morning summary", "daily_briefing"),
    
    ("how productive was I today", "productivity_analysis"),
    ("what is my focus score", "productivity_analysis"),
    
    ("sync my inbox", "sync_email"),
    ("check my mail", "sync_email"),
]

class IntentClassifier:
    def __init__(self):
        self.pipeline = None
        self._load_or_train()

    def _load_or_train(self):
        if os.path.exists(MODEL_PATH):
            try:
                self.pipeline = joblib.load(MODEL_PATH)
                return
            except Exception as e:
                print(f"Failed to load intent model: {e}")

        # Train a new one if it doesn't exist
        print("Training new Intent Classifier pipeline...")
        X, y = zip(*TRAINING_DATA)
        
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(ngram_range=(1, 2))),
            ('clf', RandomForestClassifier(n_estimators=50, random_state=42))
        ])
        
        self.pipeline.fit(X, y)
        self.save_model()

    def save_model(self):
        joblib.dump(self.pipeline, MODEL_PATH)

    def predict_intent(self, text):
        if not text or len(text.strip()) < 3:
            return "unknown"
            
        probs = self.pipeline.predict_proba([text])[0]
        max_prob = max(probs)
        
        # Confidence threshold. If it's too generic, assume we need the LLM.
        if max_prob < 0.4:
            return "complex_query"
            
        intent = self.pipeline.classes_[probs.argmax()]
        return intent

# Singleton instance
intent_engine = IntentClassifier()
