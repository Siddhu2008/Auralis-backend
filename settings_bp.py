from flask import Blueprint, jsonify, request
from utils.jwt_handler import decode_token
from models.user_settings import (
    get_or_create_user_settings,
    update_user_settings,
    reset_settings_to_default,
)
from models.user_preference import get_preferences, set_preference
from models.user import User
from database import db


settings_bp = Blueprint("settings", __name__)


def get_current_user_id():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        payload = decode_token(token)
        return payload.get("user_id")
    except Exception:
        return None


@settings_bp.route("", methods=["GET"])
def get_settings():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    settings = get_or_create_user_settings(user_id)
    prefs = get_preferences(user_id)
    return jsonify({
        "settings": settings.to_dict(),
        "meta": {
            "two_factor_enabled": prefs.get("two_factor_enabled", False),
            "session_devices": prefs.get("session_devices", []),
            "login_history": prefs.get("login_history", []),
            "connected_email_accounts": prefs.get("connected_email_accounts", ["Primary"]),
            "integrations": prefs.get("integrations", {
                "googleCalendar": False,
                "outlook": False,
                "slack": False,
                "notion": False,
                "zoom": False,
                "crm": False,
            }),
            "phone_number": prefs.get("phone_number", ""),
            "detect_conflicts": prefs.get("detect_conflicts", True),
        },
    }), 200


@settings_bp.route("", methods=["PUT"])
def put_settings():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    meta_keys = {"two_factor_enabled", "session_devices", "login_history", "connected_email_accounts", "integrations", "phone_number", "detect_conflicts"}
    model_payload = {}
    for key, value in data.items():
        if key in meta_keys:
            set_preference(user_id, key, value)
        else:
            model_payload[key] = value

    updated, errors = update_user_settings(user_id, model_payload)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    prefs = get_preferences(user_id)
    return jsonify({
        "settings": updated,
        "meta": {
            "two_factor_enabled": prefs.get("two_factor_enabled", False),
            "session_devices": prefs.get("session_devices", []),
            "login_history": prefs.get("login_history", []),
            "connected_email_accounts": prefs.get("connected_email_accounts", ["Primary"]),
            "integrations": prefs.get("integrations", {
                "googleCalendar": False,
                "outlook": False,
                "slack": False,
                "notion": False,
                "zoom": False,
                "crm": False,
            }),
            "phone_number": prefs.get("phone_number", ""),
            "detect_conflicts": prefs.get("detect_conflicts", True),
        },
    }), 200


@settings_bp.route("/reset", methods=["PATCH"])
def reset_settings():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    settings = reset_settings_to_default(user_id)
    set_preference(user_id, "two_factor_enabled", False)
    set_preference(user_id, "session_devices", [])
    set_preference(user_id, "login_history", [])
    set_preference(user_id, "connected_email_accounts", ["Primary"])
    set_preference(user_id, "integrations", {
        "googleCalendar": False,
        "outlook": False,
        "slack": False,
        "notion": False,
        "zoom": False,
        "crm": False,
    })
    set_preference(user_id, "phone_number", "")
    set_preference(user_id, "detect_conflicts", True)
    return jsonify({"settings": settings}), 200


@settings_bp.route("/privacy/clear-chat", methods=["POST"])
def clear_chat_history():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    set_preference(user_id, "chat_history_cleared_at", request.headers.get("X-Request-Time", "now"))
    return jsonify({"message": "Chat history clear request accepted"}), 200


@settings_bp.route("/privacy/reset-ai-memory", methods=["POST"])
def reset_ai_memory():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    set_preference(user_id, "ai_memory_reset_at", request.headers.get("X-Request-Time", "now"))
    return jsonify({"message": "AI memory reset request accepted"}), 200


@settings_bp.route("/security/change-password", methods=["POST"])
def change_password():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not isinstance(new_password, str) or len(new_password) < 8:
        return jsonify({"error": "new_password must be at least 8 characters"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if user.password_hash and not user.verify_password(current_password):
        return jsonify({"error": "Current password is incorrect"}), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify({"message": "Password updated successfully"}), 200
