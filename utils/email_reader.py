import imaplib
import email
from email.header import decode_header
import os
import datetime

def fetch_recent_emails(limit=10):
    """
    Connects to the IMAP server and fetches recent emails for analysis.
    Returns a list of dicts: [{'subject': ..., 'from': ..., 'body': ..., 'date': ...}]
    """
    host = 'imap.gmail.com' # Standardizing on Gmail as per earlier SMTP config
    user = os.getenv('MAIL_USERNAME')
    password = os.getenv('MAIL_PASSWORD')

    if not user or not password:
        return []

    emails_data = []
    try:
        # Connect to server
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select("inbox")

        # Search for unread emails or today's emails
        # For simplicity and demo, we'll fetch the last 10 messages
        status, messages = mail.search(None, 'ALL')
        if status != 'OK':
            return []

        message_ids = messages[0].split()
        # Get the latest 'limit' messages
        for i in range(len(message_ids)-1, len(message_ids)-1-limit, -1):
            if i < 0: break
            
            res, msg_data = mail.fetch(message_ids[i], "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    # Decode Subject
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")
                    
                    # Decode From
                    from_ = msg.get("From")
                    
                    # Get Date
                    date_ = msg.get("Date")

                    # Get Body
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition"))
                            try:
                                payload = part.get_payload(decode=True)
                                if payload and content_type == "text/plain" and "attachment" not in content_disposition:
                                    body = payload.decode()
                                    break
                            except:
                                pass
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode()

                    emails_data.append({
                        "subject": subject,
                        "from": from_,
                        "date": date_,
                        "body": body[:1000] # Limit body length for AI context
                    })
        
        mail.logout()
        return emails_data

    except Exception as e:
        print(f"IMAP Error: {e}")
        return []

def extract_scheduling_info(emails_list):
    """
    Helper to filter emails that look like they involve scheduling or deadlines.
    In a real app, we'd pass this to the LLM.
    """
    keywords = ["schedule", "meet", "interview", "call", "deadline", "today", "tomorrow"]
    filtered = []
    for em in emails_list:
        content = (em['subject'] + " " + em['body']).lower()
        if any(kw in content for kw in keywords):
            filtered.append(em)
    return filtered
