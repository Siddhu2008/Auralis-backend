import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import time
import socket

def _send_raw_email(recipient_email, subject, body_html, attachments=None):
    """Internal helper to send email with robust DNS/SMTP handling"""
    sender_email = os.getenv('MAIL_USERNAME')
    sender_password = os.getenv('MAIL_PASSWORD')

    if not sender_email or not sender_password:
        print("Error: MAIL_USERNAME or MAIL_PASSWORD not found in .env")
        return False

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject
    
    # Attach HTML body
    msg.attach(MIMEText(body_html, 'html'))
    
    # Attach files if provided
    if attachments:
        from email.mime.base import MIMEBase
        from email import encoders
        for filename, content in attachments:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={filename}')
            msg.attach(part)

    max_retries = 3
    retry_delay = 2
    host = 'smtp.gmail.com'
    
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = "192.178.211.108" # Hardcoded fallback

    for attempt in range(max_retries):
        try:
            server = None
            try:
                # Try Port 587
                server = smtplib.SMTP(ip, 587, timeout=20)
                server.ehlo(host)
                server.starttls()
                server.ehlo(host)
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, recipient_email, msg.as_string())
                server.quit()
                return True
            except Exception:
                # Fallback to Port 465
                if server: 
                    try: server.close()
                    except: pass
                server = smtplib.SMTP_SSL(ip, 465, timeout=20)
                server.ehlo(host)
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, recipient_email, msg.as_string())
                server.quit()
                return True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                print(f"Final email failure: {e}")
                return False

def send_email_otp(recipient_email, otp):
    """Sends login OTP email"""
    subject = "Your AURALIS Login OTP"
    body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #f4f4f4; padding: 20px; border-radius: 10px;">
          <h2 style="color: #4A90E2;">AURALIS Login</h2>
          <p>Hello,</p>
          <p>Your One-Time Password (OTP) for logging in is:</p>
          <h1 style="background-color: #fff; padding: 10px; border-radius: 5px; text-align: center; letter-spacing: 5px;">{otp}</h1>
          <p>This code will expire in 5 minutes.</p>
          <p>If you did not request this, please ignore this email.</p>
          <br>
          <p style="font-size: 12px; color: #888;">The AURALIS Team</p>
        </div>
      </body>
    </html>
    """
    return _send_raw_email(recipient_email, subject, body)

def send_notification_email(recipient_email, title, start_time, type='schedule'):
    """Sends a notification email for meetings/schedules"""
    from utils.calendar_helper import generate_ics_content, generate_google_calendar_link
    
    attachments = []
    calendar_link_html = ""

    if type == 'schedule':
        subject = f"Meeting Scheduled: {title}"
        message = f"A new meeting <b>{title}</b> has been scheduled for <b>{start_time}</b>."
        
        # Generate ICS
        ics_data = generate_ics_content(title, start_time)
        attachments.append((f"meeting-{int(time.time())}.ics", ics_data))
        
        # Generate Google Link
        gcal_link = generate_google_calendar_link(title, start_time)
        calendar_link_html = f"""
        <div style="margin-top: 20px; text-align: center;">
            <a href="{gcal_link}" style="background-color: #4A90E2; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">Add to Google Calendar</a>
        </div>
        """
    else:
        subject = f"Meeting Saved: {title}"
        message = f"The meeting <b>{title}</b> has been successfully saved to your history."

    body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #f4f4f4; padding: 20px; border-radius: 10px;">
          <h2 style="color: #4A90E2;">AURALIS Notification</h2>
          <p>Hello,</p>
          <p>{message}</p>
          {calendar_link_html}
          <p>You can view the details in your dashboard or check the attached calendar invitation.</p>
          <br>
          <p style="font-size: 12px; color: #888;">The AURALIS Team</p>
        </div>
      </body>
    </html>
    """
    return _send_raw_email(recipient_email, subject, body, attachments=attachments)
