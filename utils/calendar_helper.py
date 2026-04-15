from icalendar import Calendar, Event
from datetime import datetime
import urllib.parse

def generate_ics_content(title, start_time_iso, duration_minutes=60):
    """
    Generates a string formatted as an iCalendar (.ics) file.
    start_time_iso should be in ISO format (e.g. 2023-10-27T10:00:00)
    """
    cal = Calendar()
    cal.add('prodid', '-//Auralis//auralis.app//')
    cal.add('version', '2.0')

    event = Event()
    event.add('summary', title)
    
    # Parse ISO time
    try:
        dt = datetime.fromisoformat(start_time_iso.replace('Z', ''))
    except:
        dt = datetime.utcnow()
        
    event.add('dtstart', dt)
    event.add('dtend', datetime.fromtimestamp(dt.timestamp() + (duration_minutes * 60)))
    event.add('dtstamp', datetime.utcnow())
    event.add('description', f'Auralis Meeting: {title}')
    
    cal.add_component(event)
    return cal.to_ical()

def generate_google_calendar_link(title, start_time_iso, duration_minutes=60):
    """
    Generates a direct 'Add to Google Calendar' URL.
    """
    try:
        dt = datetime.fromisoformat(start_time_iso.replace('Z', ''))
    except:
        dt = datetime.utcnow()
        
    dt_end = datetime.fromtimestamp(dt.timestamp() + (duration_minutes * 60))
    
    # Format: YYYYMMDDTHHmmSSZ
    fmt = "%Y%m%dT%H%M%SZ"
    dates = f"{dt.strftime(fmt)}/{dt_end.strftime(fmt)}"
    
    base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
    params = {
        "text": title,
        "dates": dates,
        "details": f"Auralis AI Meeting: {title}",
        "sf": "true",
        "output": "xml"
    }
    
    return f"{base_url}&{urllib.parse.urlencode(params)}"


def create_google_calendar_event(
    owner_email,
    *,
    title,
    start_time,
    meeting_link,
    attendees=None,
    end_time=None,
):
    """
    Lightweight integration point for Google Calendar API.
    Returns event metadata suitable for persistence/logging.
    """
    attendees = attendees or []
    calendar_link = generate_google_calendar_link(title, start_time)
    return {
        "owner_email": owner_email,
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "meeting_link": meeting_link,
        "attendees": attendees,
        "calendar_link": calendar_link,
    }
