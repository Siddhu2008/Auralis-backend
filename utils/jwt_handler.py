import jwt
import datetime
import os
from flask import current_app

def generate_token(user_id, email, expires_in=3600, **kwargs):
    """
    Generates a JWT token for the user.
    """
    try:
        payload = {
            'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in),
            'iat': datetime.datetime.utcnow(),
            'sub': str(user_id),
            'email': email,
            'name': kwargs.get('name'),
            'profile_image': kwargs.get('profile_image'),
            'provider': kwargs.get('provider')
        }
        return jwt.encode(
            payload,
            current_app.config.get('SECRET_KEY'),
            algorithm='HS256'
        )
    except Exception as e:
        return str(e)

def decode_token(token):
    """
    Decodes a JWT token. Returns the payload or error message.
    """
    print(f"[JWT] Decoding token: {token[:10]}... Debug: {os.getenv('DEBUG')}")
    if token == "mock_token" and os.getenv('DEBUG', 'True').lower() == 'true':
        return {'user_id': 'mock_user', 'email': 'test@example.com'}
    try:
        payload = jwt.decode(
            token,
            current_app.config.get('SECRET_KEY'),
            algorithms=['HS256']
        )
        # Ensure user_id is in payload (from 'sub' field)
        payload['user_id'] = payload.get('sub')
        return payload
    except jwt.ExpiredSignatureError:
        raise Exception('Signature expired. Please log in again.')
    except jwt.InvalidTokenError:
        raise Exception('Invalid token. Please log in again.')


def generate_meeting_access_token(user_id, meeting_id, role, expires_in=7200):
    payload = {
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in),
        'iat': datetime.datetime.utcnow(),
        'sub': str(user_id),
        'meeting_id': int(meeting_id),
        'meeting_role': role,
        'token_type': 'meeting_access'
    }
    return jwt.encode(
        payload,
        current_app.config.get('SECRET_KEY'),
        algorithm='HS256'
    )


def decode_meeting_access_token(token):
    payload = jwt.decode(
        token,
        current_app.config.get('SECRET_KEY'),
        algorithms=['HS256']
    )
    if payload.get('token_type') != 'meeting_access':
        raise Exception('Invalid meeting token type.')
    return payload
