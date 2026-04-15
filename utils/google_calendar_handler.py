import os
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from models.user import User
from database import db

def get_calendar_service(user_id):
    """
    Returns a Google Calendar API service instance for the given user.
    """
    user = User.query.get(user_id)
    if not user or not user.google_refresh_token:
        return None

    creds = Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/calendar.events"]
    )

    return build("calendar", "v3", credentials=creds)

def sync_event_to_google(user_id, schedule_data):
    """
    Creates an event on the user's primary Google Calendar.
    """
    service = get_calendar_service(user_id)
    if not service:
        print(f"[GCal] No linked account for user {user_id}")
        return False

    try:
        start_time = schedule_data.get('start_time')
        # Ensure it's in the format Google expects (RFC3339)
        if start_time.endswith('Z'):
            start_time = start_time.replace('Z', '+00:00')

        duration = schedule_data.get('duration_minutes', 30)
        end_time = (datetime.fromisoformat(start_time) + timedelta(minutes=duration)).isoformat()

        event = {
            'summary': schedule_data.get('title', 'Auralis Meeting'),
            'description': 'Scheduled via Auralis AI Assistant',
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
            },
            'attendees': [{'email': e} for e in schedule_data.get('participants', [])],
            'reminders': {
                'useDefault': True,
            },
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        print(f"[GCal] Event created: {created_event.get('htmlLink')}")
        return True
    except Exception as e:
        print(f"[GCal] Sync error: {e}")
        return False

def delete_google_event(user_id, g_event_id):
    """
    Deletes an event from Google Calendar. 
    (Note: Requires storing Google's event ID in our local Schedule model)
    """
    service = get_calendar_service(user_id)
    if not service: return False

    try:
        service.events().delete(calendarId='primary', eventId=g_event_id).execute()
        return True
    except Exception as e:
        print(f"[GCal] Delete error: {e}")
        return False
