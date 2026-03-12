# Imports moved inside methods for Eventlet compatibility
from datetime import datetime
from database import db

class HabitClusterService:
    def __init__(self):
        self.k_meetings = 3

    def predict_optimal_meeting_times(self, user_id, limit=3):
        """
        Uses historical meeting data to cluster and predict preferred meeting times.
        Returns the top predicted time slots (hour of day as integer, 0-23).
        """
        import numpy as np
        from sklearn.cluster import KMeans
        try:
            # Fetch past meeting start times to find clusters
            # For a real twin, we'd also pull external calendar data
            from models.schedule import Schedule  # lazy import to avoid circular dependency
            schedules = Schedule.query.filter_by(user_id=user_id).all()
            if len(schedules) < 3:
                # Not enough data for K-Means, fallback to heuristics
                return [10, 14, 16] # 10 AM, 2 PM, 4 PM

            hours = []
            for s in schedules:
                try:
                    dt = datetime.fromisoformat(s.start_time.replace('Z', '+00:00'))
                    hours.append([dt.hour])
                except Exception:
                    continue
            
            if len(hours) < self.k_meetings:
                return [10, 14, 16]

            X = np.array(hours)
            kmeans = KMeans(n_clusters=min(self.k_meetings, len(set([h[0] for h in hours]))), random_state=42)
            kmeans.fit(X)
            
            # Predict top centers rounded to nearest hour
            centers = kmeans.cluster_centers_.flatten()
            preferred_hours = sorted([int(round(c)) for c in centers])
            return preferred_hours
        except Exception as e:
            print(f"Habit cluster error: {e}")
            return [10, 14, 16]

    def get_user_active_hours(self, user_id):
        """
        Analyzes user_behavior_log to find when the user is most active.
        """
        import numpy as np
        try:
            from models.user_behavior import UserBehaviorLog  # lazy import to avoid circular dependency
            logs = UserBehaviorLog.query.filter_by(user_id=user_id).all()
            if not logs:
                return {"start": 9, "end": 17} # Default 9 to 5
                
            hours = [log.active_hour for log in logs]
            q1 = int(np.percentile(hours, 25))
            q3 = int(np.percentile(hours, 75))
            return {"start": max(0, q1), "end": min(23, q3)}
        except Exception:
            return {"start": 9, "end": 17}

    def get_autonomous_recommendations(self, user_id):
        """
        Synthesizes active hours and meeting patterns into actionable autonomous recommendations.
        """
        active_hours = self.get_user_active_hours(user_id)
        preferred_times = self.predict_optimal_meeting_times(user_id)
        current_hour = datetime.utcnow().hour
        
        recommendations = []
        
        # 1. Check for Active Period
        if current_hour < active_hours["start"]:
            recommendations.append("Morning Strategy: Prepare daily briefing and prioritize deep work tasks.")
        elif current_hour > active_hours["end"]:
            recommendations.append("Evening Wind-down: Summarize today's achievements and prepare tomorrow's agenda.")
        
        # 2. Check for Meeting Preference
        if any(abs(current_hour - pt) <= 1 for pt in preferred_times):
            recommendations.append("Optimal Meeting Window: You usually handle communications now. Shall I check for pending syncs?")
        
        # 3. Handle Deep Work Slot
        if active_hours["start"] + 2 <= current_hour <= active_hours["start"] + 4:
             recommendations.append("Peak Focus Window: Ideal time for 'Autonomous Deep Work' - blocking distractors.")
             
        return recommendations

habit_engine = HabitClusterService()
