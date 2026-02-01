from utils.calendar_helper import generate_ics_content, generate_google_calendar_link
from datetime import datetime

title = "Test Meeting"
start = datetime.utcnow().isoformat()

print("Testing ICS Generation...")
ics = generate_ics_content(title, start)
print(ics.decode()[:100], "...")

print("\nTesting GCal Link...")
link = generate_google_calendar_link(title, start)
print(link)
