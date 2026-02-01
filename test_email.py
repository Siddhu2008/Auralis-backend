import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Try to load existing .env
load_dotenv()

def test_smtp():
    sender_email = os.getenv('MAIL_USERNAME')
    sender_password = os.getenv('MAIL_PASSWORD')
    recipient_email = sender_email # Send to self for test

    print(f"Testing SMTP with {sender_email}...")
    
    if not sender_email or not sender_password:
        print("ERROR: MAIL_USERNAME or MAIL_PASSWORD missing in .env")
        return

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = "SMTP Diagnostic Test"
    msg.attach(MIMEText("This is a test email to verify SMTP configuration.", 'plain'))

    try:
        print("Connecting to smtp.gmail.com:587...")
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        
        print("Starting TLS...")
        server.starttls()
        
        print(f"Attempting login for {sender_email}...")
        server.login(sender_email, sender_password)
        
        print("Sending mail...")
        server.sendmail(sender_email, recipient_email, msg.as_string())
        
        server.quit()
        print("SUCCESS: Email sent successfully!")
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Authentication failed. This usually means:")
        print("1. Your password is incorrect.")
        print("2. You need to use a Google 'App Password' instead of your regular password.")
        print("3. 'Less secure app access' is disabled (Google disabled this in 2022).")
    except smtplib.SMTPConnectError:
        print("ERROR: Could not connect to the SMTP server. Check your internet connection or firewall.")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {str(e)}")

if __name__ == "__main__":
    test_smtp()
