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
    
    for attempt in range(max_retries):
        try:
            server = None
            try:
                # Try Port 587
                server = smtplib.SMTP(host, 587, timeout=20)
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, recipient_email, msg.as_string())
                server.quit()
                return True
            except Exception:
                # Fallback to Port 465
                if server: 
                    try: server.close()
                    except: pass
                server = smtplib.SMTP_SSL(host, 465, timeout=20)
                server.ehlo()
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

def send_email_custom(recipient_email, subject, body_text):
    """Sends a custom email drafted by the AI Assistant"""
    body_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #f4f4f4; padding: 20px; border-radius: 10px; border: 1px solid #ddd;">
          <h2 style="color: #4A90E2; border-bottom: 2px solid #4A90E2; padding-bottom: 10px;">AURALIS Assistant</h2>
          <p style="font-size: 16px; line-height: 1.6;">{body_text.replace('\n', '<br>')}</p>
          <br>
          <hr style="border: 0; border-top: 1px solid #eee;">
          <p style="font-size: 12px; color: #888; text-align: center;">This message was dispatched via Auralis Neural Executive Assistant.</p>
        </div>
      </body>
    </html>
    """
    return _send_raw_email(recipient_email, subject, body_html)

def send_daily_digest_email(recipient_email, user_name, tasks, meetings):
    """Sends a daily digest email containing pending tasks and today's meetings."""
    subject = "AURALIS: Your Daily Briefing"
    
    tasks_html = ""
    if tasks:
        tasks_html = "<ul>"
        for t in tasks:
            title = t.get('title', 'Untitled Task') if isinstance(t, dict) else getattr(t, 'title', 'Untitled Task')
            tasks_html += f"<li style='margin-bottom: 8px;'>{title}</li>"
        tasks_html += "</ul>"
    else:
        tasks_html = "<p style='color: #666; font-style: italic;'>No pending tasks! Great job!</p>"
        
    meetings_html = ""
    if meetings:
        meetings_html = "<ul>"
        for m in meetings:
            title = m.get('title', 'Untitled Meeting') if isinstance(m, dict) else getattr(m, 'title', 'Untitled Meeting')
            # Extract formatted time if available
            start = m.get('scheduled_start_at') if isinstance(m, dict) else getattr(m, 'scheduled_start_at', None)
            time_str = start.strftime('%I:%M %p') if start else "Time TBD"
            meetings_html += f"<li style='margin-bottom: 8px;'><b>{time_str}</b> - {title}</li>"
        meetings_html += "</ul>"
    else:
        meetings_html = "<p style='color: #666; font-style: italic;'>No meetings scheduled for today.</p>"

    body_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; padding: 20px; color: #333; background-color: #f9fafb;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 30px; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
          <div style="text-align: center; margin-bottom: 20px;">
            <h1 style="color: #4A90E2; margin: 0; font-size: 24px; letter-spacing: 1px;">AURALIS</h1>
            <p style="color: #6b7280; font-size: 14px; margin-top: 5px;">Daily Executive Briefing</p>
          </div>
          
          <h2 style="font-size: 18px; color: #1f2937; margin-top: 0;">Good morning, {user_name}</h2>
          <p style="color: #4b5563; line-height: 1.5;">Here is a summary of what's on your agenda for today to help you stay focused and productive.</p>
          
          <div style="margin-top: 30px;">
            <h3 style="color: #4f46e5; border-bottom: 2px solid #e0e7ff; padding-bottom: 8px; font-size: 16px;">📅 Today's Meetings</h3>
            {meetings_html}
          </div>
          
          <div style="margin-top: 30px;">
            <h3 style="color: #10b981; border-bottom: 2px solid #d1fae5; padding-bottom: 8px; font-size: 16px;">✅ Pending Tasks</h3>
            {tasks_html}
          </div>
          
          <hr style="border: 0; border-top: 1px solid #f3f4f6; margin-top: 40px; margin-bottom: 20px;">
          <div style="text-align: center;">
            <p style="font-size: 12px; color: #9ca3af; margin: 0;">Sent autonomously by Auralis AI</p>
            <p style="font-size: 11px; color: #d1d5db; margin-top: 5px;">You can configure your notification settings in the app dashboard.</p>
          </div>
        </div>
      </body>
    </html>
    """
    
    return _send_raw_email(recipient_email, subject, body_html)
