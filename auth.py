import jwt
import os
from flask import Blueprint, request, jsonify, current_app
from utils.otp_handler import generate_otp, store_otp, verify_otp
from utils.email_handler import send_email_otp
from utils.jwt_handler import generate_token
from models.user import create_user, find_user_by_email, find_user_by_google_id
from models.user_settings import create_default_settings_for_user
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/send-otp', methods=['POST'])
def send_otp():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing request body'}), 400
            
        email = data.get('email')
        if not email:
            return jsonify({'error': 'Email is required'}), 400
            
        otp = generate_otp()
        store_otp(email, otp)
        
        # Send Email
        email_sent = send_email_otp(email, otp)
        
        if email_sent:
            return jsonify({'message': 'OTP sent to your email'}), 200
        else:
            # Fallback for dev mode/error
            print(f" [AUTH DEBUG] OTP for {email}: {otp} ")
            return jsonify({'message': 'Failed to send email (Check .env). OTP logged to console for Dev.'}), 200
    except Exception as e:
        print(f"OTP Send Error: {e}")
        return jsonify({'error': 'Failed to process request', 'details': str(e)}), 500

@auth_bp.route('/verify-otp', methods=['POST'])
def verify():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing request body'}), 400
            
        email = data.get('email')
        otp = data.get('otp')
        
        if not email or not otp:
            return jsonify({'error': 'Email and OTP are required'}), 400
            
        if verify_otp(email, otp):
            # Find or create user
            user = find_user_by_email(email)
            if not user:
                user = create_user(email=email, name=email.split('@')[0])
            else:
                create_default_settings_for_user(user['id'])
            
            # Generate JWT with database user ID
            token = generate_token(user_id=user['id'], email=user['email'])
            return jsonify({'token': token, 'user': {'email': user['email'], 'name': user['name']}}), 200
        else:
            return jsonify({'error': 'Invalid or expired OTP'}), 401
    except Exception as e:
        print(f"OTP Verify Error: {e}")
        return jsonify({'error': 'Verification failed', 'details': str(e)}), 500


@auth_bp.route('/google', methods=['POST'])
def google_auth():
    """
    Verify Google OAuth token from frontend and create/login user
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        token = data.get('credential')  # Google ID token from frontend
        if not token:
            return jsonify({'error': 'No Google credential provided'}), 400
        
        idinfo = None
        is_debug = os.getenv('DEBUG', 'True').lower() == 'true'

        if is_debug:
            print("[AUTH] Development Mode: Decoding Google Token locally (Offline-friendly)")
            # In Dev mode, we decode without verification to bypass DNS/API issues
            # google-auth is strict and requires internet for certs. PyJWT allows local decoding.
            # security: verify_signature=False is ONLY for DEV mode.
            try:
                idinfo = jwt.decode(token, options={"verify_signature": False})
            except Exception as jwt_err:
                print(f"JWT Decode Error: {jwt_err}")
                return jsonify({'error': 'Invalid token format'}), 400
        else:
            print("[AUTH] Production Mode: Verifying Google Token via API")
            # In Production, we MUST verify properly
            try:
                idinfo = id_token.verify_oauth2_token(
                    token, 
                    google_requests.Request(), 
                    os.getenv('GOOGLE_CLIENT_ID')
                )
            except ValueError as val_err:
                return jsonify({'error': 'Invalid Google token', 'details': str(val_err)}), 401
            except Exception as api_err:
                print(f"Google API Verification Error: {api_err}")
                return jsonify({'error': 'Could not reach Google verification servers', 'details': str(api_err)}), 503

        if not idinfo:
            return jsonify({'error': 'Failed to extract user info from token'}), 400

        # Extract user info
        google_id = idinfo.get('sub')
        email = idinfo.get('email')
        
        if not google_id or not email:
            return jsonify({'error': 'Google token missing required fields (sub/email)'}), 400
            
        name = email.split('@')[0]
        
        # Find or create user
        user = find_user_by_google_id(google_id)
        if not user:
            user = find_user_by_email(email)
            if not user:
                user = create_user(email=email, name=name, google_id=google_id)
            else:
                # User exists by email, link Google ID if not present
                # (Optional logic, for now just ensure they can log in)
                create_default_settings_for_user(user['id'])
        else:
            create_default_settings_for_user(user['id'])
        
        # Generate our app's JWT
        user_id = user.get('_id') or user.get('id')
        if not user_id:
            print("DEBUG: user object missing id field:", user)
            return jsonify({'error': 'User object missing id'}), 500
        jwt_token = generate_token(user_id=user_id, email=user['email'])

        return jsonify({
            'token': jwt_token,
            'user': {
                'email': user['email'],
                'name': user['name']
            }
        }), 200
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"CRITICAL: Global Auth Error: {str(e)}")
        print(error_details)
        return jsonify({
            'error': 'Internal Authentication failure',
            'details': str(e)
        }), 500
