import imaplib
import email
from email.header import decode_header
import email.utils
import os
import re
from datetime import datetime


# Simple time-based cache: (limit, user, password) -> (timestamp, data)
_email_cache = {}
_CACHE_TTL = 120  # 2 minutes

def fetch_recent_emails(limit=10):
    """
    Connects to the IMAP server and fetches recent emails for analysis.
    Returns a list of dicts:
    [{'subject': ..., 'from': ..., 'body': ..., 'date': ..., 'parsed_date': ...}]
    """
    host = 'imap.gmail.com'
    user = os.getenv('MAIL_USERNAME')
    password = os.getenv('MAIL_PASSWORD')

    if not user or not password:
        return []

    # Cache Check
    cache_key = (limit, user, password)
    if cache_key in _email_cache:
        ts, data = _email_cache[cache_key]
        if datetime.now().timestamp() - ts < _CACHE_TTL:
            print(f"[CACHE] Returning cached emails for {user}")
            return data

    emails_data = []
    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select("inbox")

        status, messages = mail.search(None, 'ALL')
        if status != 'OK':
            return []

        message_ids = messages[0].split()
        for i in range(len(message_ids)-1, len(message_ids)-1-limit, -1):
            if i < 0:
                break

            res, msg_data = mail.fetch(message_ids[i], "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])

                    # Decode Subject
                    subject_header = msg.get("Subject", "")
                    subject, encoding = decode_header(subject_header)[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(
                            encoding if encoding else "utf-8",
                            errors="replace"
                        )

                    # Decode From
                    from_ = msg.get("From")

                    # Get Date and parse it
                    date_string = msg.get("Date")
                    parsed_date = None
                    if date_string:
                        try:
                            parsed_date = email.utils.parsedate_to_datetime(
                                date_string
                            )
                        except Exception:
                            parsed_date = datetime.utcnow()
                    else:
                        parsed_date = datetime.utcnow()

                    # Get Body
                    body = ""
                    html_body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            disp = str(part.get("Content-Disposition"))
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    if content_type == "text/plain" and \
                                       "attachment" not in disp:
                                        body = payload.decode(errors="replace")
                                        break
                                    elif content_type == "text/html":
                                        html_body = payload.decode(
                                            errors="replace"
                                        )
                            except Exception:
                                pass
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors="replace")

                    # Fallback to HTML if text is empty
                    if not body and html_body:
                        # Simple tag stripping
                        body = re.sub(r'<[^>]+>', '', html_body)
                        body = re.sub(r'\s+', ' ', body).strip()

                    emails_data.append({
                        "id": message_ids[i].decode(),
                        "subject": subject,
                        "from": from_,
                        "date": date_string,
                        "parsed_date": parsed_date.isoformat() if parsed_date else None,
                        "body": body[:5000]
                    })

        mail.logout()
        _email_cache[cache_key] = (datetime.now().timestamp(), emails_data)
        return emails_data

    except Exception as e:
        print(f"IMAP Error: {e}")
        return []


def extract_scheduling_info(emails_list):
    """
    Helper to filter emails that involving scheduling.
    """
    keywords = ["schedule", "meet", "interview", "call", "deadline"]
    filtered = []
    for em in emails_list:
        content = (em['subject'] + " " + em['body']).lower()
        if any(kw in content for kw in keywords):
            filtered.append(em)
    return filtered
