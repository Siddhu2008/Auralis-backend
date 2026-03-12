import os
import requests
from datetime import datetime, timedelta
from database import db
from models.user import User
from models.meeting import create_meeting, Meeting
from models.task import create_task
import logging

logger = logging.getLogger(__name__)

class GoogleSyncService:
    def __init__(self):
        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')

    def refresh_user_token(self, user):
        """Refreshes the Google access token if it's expired or about to expire."""
        if not user.google_refresh_token:
            return False
            
        # Check if expired (with 1 min buffer)
        if user.google_token_expiry and datetime.utcnow() < (user.google_token_expiry - timedelta(minutes=1)):
            return True

        url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": user.google_refresh_token,
            "grant_type": "refresh_token"
        }
        
        try:
            res = requests.post(url, data=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                user.google_access_token = data['access_token']
                expires_in = data.get('expires_in', 3600)
                user.google_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
                db.session.commit()
                return True
            else:
                logger.error(f"[GoogleSync] Token refresh failed: {res.text}")
                return False
        except Exception as e:
            logger.error(f"[GoogleSync] Token refresh exception: {e}")
            return False

    def sync_calendar(self, user_id):
        """Fetches real events from Google Calendar and syncs to Auralis Meetings."""
        user = User.query.get(user_id)
        if not user or not self.refresh_user_token(user):
            return 0

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        headers = {"Authorization": f"Bearer {user.google_access_token}"}
        params = {
            "timeMin": datetime.utcnow().isoformat() + "Z",
            "maxResults": 10,
            "singleEvents": True,
            "orderBy": "startTime"
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code != 200:
                return 0
                
            events = res.json().get('items', [])
            synced_count = 0
            for event in events:
                # Basic check to avoid duplicates (based on room_id as external_id)
                ext_id = f"google_{event.get('id')}"
                existing = Meeting.query.filter_by(room_id=ext_id).first()
                if not existing:
                    start_str = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
                    start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    
                    create_meeting(
                        user_id=user.id,
                        room_id=ext_id,
                        title=event.get('summary', 'Google Calendar Event'),
                        transcript="",
                        summary=event.get('description', ''),
                        status='scheduled', # Mark as scheduled since it's from calendar
                        ended_at=start_dt # Using as date
                    )
                    synced_count += 1
            return synced_count
        except Exception as e:
            logger.error(f"[GoogleSync] Calendar sync error: {e}")
            return 0

    def sync_gmail(self, user_id):
        """Fetches recent Gmail messages and potentially creates tasks."""
        user = User.query.get(user_id)
        if not user or not self.refresh_user_token(user):
            return 0

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        headers = {"Authorization": f"Bearer {user.google_access_token}"}
        params = {"maxResults": 5, "q": "is:unread"}

        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code != 200:
                return 0
                
            messages = res.json().get('messages', [])
            for msg_ref in messages:
                # Fetch full message
                msg_url = f"{url}/{msg_ref['id']}"
                msg_res = requests.get(msg_url, headers=headers, timeout=10)
                if msg_res.status_code == 200:
                    msg_data = msg_res.json()
                    snippet = msg_data.get('snippet', '')
                    # Simple heuristic: if "important" or "task" or "action" in snippet, create task
                    low_snippet = snippet.lower()
                    if any(x in low_snippet for x in ["urgent", "action", "deadline", "please"]):
                        create_task(
                            user_id=user.id,
                            title=f"Gmail Action: {snippet[:50]}...",
                            source_type="gmail",
                            source_id=msg_ref['id']
                        )
            return len(messages)
        except Exception as e:
            logger.error(f"[GoogleSync] Gmail sync error: {e}")
            return 0

google_sync_service = GoogleSyncService()
