import random
import string
import datetime

# In-memory storage for OTPs. 
# Structure: {email: {'otp': '123456', 'expires_at': datetime_obj}}
# In production, use Redis.
otp_store = {}

def generate_otp(length=6):
    """Generates a numeric OTP of given length."""
    return ''.join(random.choices(string.digits, k=length))

def store_otp(email, otp, expiry_seconds=300):
    """Stores OTP with expiration."""
    print("your opt is",otp)
    otp_store[email] = {
        'otp': otp,
        'expires_at': datetime.datetime.utcnow() + datetime.timedelta(seconds=expiry_seconds)
    }

def verify_otp(email, otp):
    """
    Verifies the OTP for the email.
    Returns True if valid, False otherwise.
    """
    if email not in otp_store:
        return False
    
    data = otp_store[email]
    
    if datetime.datetime.utcnow() > data['expires_at']:
        del otp_store[email] # Cleanup expiry
        return False
    
    if data['otp'] == otp:
        del otp_store[email] # Consume OTP
        return True
        
    return False
