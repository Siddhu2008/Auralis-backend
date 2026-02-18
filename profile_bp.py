from flask import Blueprint, request, jsonify
from database import db
from models.user import find_user_by_id, User
from utils.jwt_handler import decode_token

profile_bp = Blueprint('profile', __name__)

def get_current_user_id():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ')[1]
    try:
        payload = decode_token(token)
        return payload.get('user_id')
    except:
        return None

@profile_bp.route('/', methods=['GET'])
def get_profile():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = find_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    return jsonify({"profile": user}), 200

@profile_bp.route('/', methods=['PATCH'])
def update_profile():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    user_obj = User.query.get(user_id)
    if not user_obj:
        return jsonify({"error": "User not found"}), 404
        
    # Allowed updates
    if 'name' in data:
        user_obj.name = data['name']
    if 'profile_image' in data:
        user_obj.profile_image = data['profile_image']
        
    db.session.commit()
    return jsonify({"message": "Profile updated", "profile": user_obj.to_dict()}), 200

@profile_bp.route('/', methods=['DELETE'])
def delete_account():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_obj = User.query.get(user_id)
    if not user_obj:
        return jsonify({"error": "User not found"}), 404
        
    # Securely delete user
    db.session.delete(user_obj)
    db.session.commit()
    
    return jsonify({"message": "Account deleted successfully"}), 200
