import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import time
import socket

import resend

def _send_raw_email(recipient_email, subject, body_html, attachments=None):
    """Internal helper to send email using Resend API"""
    api_key = os.getenv('RESEND_API_KEY')
    sender_email = os.getenv('MAIL_USERNAME', 'onboarding@resend.dev')

    if not api_key:
        return False, "RESEND_API_KEY missing in environment variables"

    resend.api_key = api_key

    try:
        # For Sandbox/Onboarding, keep the sender simple
        formatted_from = sender_email if "onboarding@resend.dev" in sender_email else f"Auralis <{sender_email}>"
        
        params = {
            "from": formatted_from,
            "to": [recipient_email],
            "subject": subject,
            "html": body_html,
        }

        if attachments:
            params["attachments"] = [
                {"filename": name, "content": list(content)} # resend expects content as bytes/list
                for name, content in attachments
            ]

        r = resend.Emails.send(params)
        return True, "Success"
    except Exception as e:
        return False, f"Resend API Error: {str(e)}"

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
          <p style="font-size: 16px; line-height: 1.6;">{body_text}</p>
          <br>
          <hr style="border: 0; border-top: 1px solid #eee;">
          <p style="font-size: 12px; color: #888; text-align: center;">This message was dispatched via Auralis Neural Executive Assistant.</p>
        </div>
      </body>
    </html>
    """
    return _send_raw_email(recipient_email, subject, body_html)
