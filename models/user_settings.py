from datetime import datetime
from database import db


THEME_VALUES = {"dark", "light"}
ASSISTANT_TONE_VALUES = {"professional", "friendly", "executive", "concise"}
ASSISTANT_RESPONSE_LENGTH_VALUES = {"short", "medium", "detailed"}
ASSISTANT_AUTONOMY_VALUES = {"suggest_only", "assisted", "full"}
LANGUAGE_VALUES = {"english", "hindi", "spanish", "french", "german"}
PLATFORM_VALUES = {"zoom", "google meet", "custom"}
WEEK_DAY_VALUES = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def default_settings_payload():
    return {
        "theme_mode": "dark",
        "accent_color": "#2563eb",
        "font_size": 100,
        "assistant_tone": "professional",
        "assistant_response_length": "medium",
        "assistant_autonomy_level": "assisted",
        "daily_briefing_enabled": True,
        "auto_followups_enabled": True,
        "default_meeting_duration": 30,
        "default_meeting_platform": "google meet",
        "working_hours_start": "09:00",
        "working_hours_end": "18:00",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "buffer_time_minutes": 10,
        "prevent_past_dates": True,
        "prevent_outside_working_hours": True,
        "require_schedule_confirmation": True,
        "email_auto_categorize": True,
        "email_draft_suggestions": True,
        "require_email_approval": True,
        "trusted_contacts": [],
        "notifications_enabled": True,
        "email_notifications_enabled": True,
        "timezone": "UTC",
        "language": "english",
    }


class UserSettings(db.Model):
    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    theme_mode = db.Column(db.String(20), nullable=False, default="dark")
    accent_color = db.Column(db.String(20), nullable=False, default="#2563eb")
    font_size = db.Column(db.Integer, nullable=False, default=100)
    assistant_tone = db.Column(db.String(20), nullable=False, default="professional")
    assistant_response_length = db.Column(db.String(20), nullable=False, default="medium")
    assistant_autonomy_level = db.Column(db.String(20), nullable=False, default="assisted")
    daily_briefing_enabled = db.Column(db.Boolean, nullable=False, default=True)
    auto_followups_enabled = db.Column(db.Boolean, nullable=False, default=True)
    default_meeting_duration = db.Column(db.Integer, nullable=False, default=30)
    default_meeting_platform = db.Column(db.String(30), nullable=False, default="google meet")
    working_hours_start = db.Column(db.String(5), nullable=False, default="09:00")
    working_hours_end = db.Column(db.String(5), nullable=False, default="18:00")
    working_days = db.Column(db.JSON, nullable=False, default=["Mon", "Tue", "Wed", "Thu", "Fri"])
    buffer_time_minutes = db.Column(db.Integer, nullable=False, default=10)
    prevent_past_dates = db.Column(db.Boolean, nullable=False, default=True)
    prevent_outside_working_hours = db.Column(db.Boolean, nullable=False, default=True)
    require_schedule_confirmation = db.Column(db.Boolean, nullable=False, default=True)
    email_auto_categorize = db.Column(db.Boolean, nullable=False, default=True)
    email_draft_suggestions = db.Column(db.Boolean, nullable=False, default=True)
    require_email_approval = db.Column(db.Boolean, nullable=False, default=True)
    trusted_contacts = db.Column(db.JSON, nullable=False, default=[])
    notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    email_notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")
    language = db.Column(db.String(20), nullable=False, default="english")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "theme_mode": self.theme_mode,
            "accent_color": self.accent_color,
            "font_size": self.font_size,
            "assistant_tone": self.assistant_tone,
            "assistant_response_length": self.assistant_response_length,
            "assistant_autonomy_level": self.assistant_autonomy_level,
            "daily_briefing_enabled": self.daily_briefing_enabled,
            "auto_followups_enabled": self.auto_followups_enabled,
            "default_meeting_duration": self.default_meeting_duration,
            "default_meeting_platform": self.default_meeting_platform,
            "working_hours_start": self.working_hours_start,
            "working_hours_end": self.working_hours_end,
            "working_days": self.working_days or [],
            "buffer_time_minutes": self.buffer_time_minutes,
            "prevent_past_dates": self.prevent_past_dates,
            "prevent_outside_working_hours": self.prevent_outside_working_hours,
            "require_schedule_confirmation": self.require_schedule_confirmation,
            "email_auto_categorize": self.email_auto_categorize,
            "email_draft_suggestions": self.email_draft_suggestions,
            "require_email_approval": self.require_email_approval,
            "trusted_contacts": self.trusted_contacts or [],
            "notifications_enabled": self.notifications_enabled,
            "email_notifications_enabled": self.email_notifications_enabled,
            "timezone": self.timezone,
            "language": self.language,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class SettingsAuditLog(db.Model):
    __tablename__ = "settings_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    changes = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "changes": self.changes,
            "created_at": self.created_at.isoformat(),
        }


def get_user_settings(user_id):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    return settings.to_dict() if settings else None


def get_or_create_user_settings(user_id, detected_timezone=None):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        # Backfill any NULL boolean/default fields caused by ALTER TABLE (no default clause)
        defaults = default_settings_payload()
        dirty = False
        for key, default_value in defaults.items():
            current = getattr(settings, key, None)
            if current is None:
                setattr(settings, key, default_value)
                dirty = True
        if dirty:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return settings

    payload = default_settings_payload()
    if detected_timezone and is_valid_timezone(detected_timezone):
        payload["timezone"] = detected_timezone
    settings = UserSettings(user_id=user_id, **payload)
    db.session.add(settings)
    db.session.commit()
    return settings


def create_default_settings_for_user(user_id):
    existing = UserSettings.query.filter_by(user_id=user_id).first()
    if existing:
        return existing.to_dict()

    settings = UserSettings(user_id=user_id, **default_settings_payload())
    db.session.add(settings)
    db.session.commit()
    return settings.to_dict()


def reset_settings_to_default(user_id):
    settings = get_or_create_user_settings(user_id)
    defaults = default_settings_payload()
    for key, value in defaults.items():
        setattr(settings, key, value)
    db.session.commit()
    return settings.to_dict()


def log_settings_change(user_id, changes):
    audit = SettingsAuditLog(user_id=user_id, changes=changes)
    db.session.add(audit)
    db.session.commit()
    return audit.to_dict()


def is_valid_timezone(value):
    if not isinstance(value, str) or not value.strip():
        return False
    if value.upper() == "UTC":
        return True
    return "/" in value and len(value) <= 64


def validate_settings_update(data):
    if not isinstance(data, dict):
        return {"_error": "Invalid payload type"}

    errors = {}

    def as_lower_str(key):
        val = data.get(key)
        return val.lower().strip() if isinstance(val, str) else val

    if "theme_mode" in data:
        if as_lower_str("theme_mode") not in THEME_VALUES:
            errors["theme_mode"] = "theme_mode must be dark or light"

    if "accent_color" in data:
        val = data.get("accent_color")
        if not isinstance(val, str) or not val.startswith("#") or len(val) not in (4, 7):
            errors["accent_color"] = "accent_color must be a hex value"

    if "font_size" in data:
        val = data.get("font_size")
        if not isinstance(val, int) or val < 85 or val > 130:
            errors["font_size"] = "font_size must be between 85 and 130"

    if "assistant_tone" in data:
        if as_lower_str("assistant_tone") not in ASSISTANT_TONE_VALUES:
            errors["assistant_tone"] = f"assistant_tone must be one of {sorted(ASSISTANT_TONE_VALUES)}"

    if "assistant_response_length" in data:
        if as_lower_str("assistant_response_length") not in ASSISTANT_RESPONSE_LENGTH_VALUES:
            errors["assistant_response_length"] = f"assistant_response_length must be one of {sorted(ASSISTANT_RESPONSE_LENGTH_VALUES)}"

    if "assistant_autonomy_level" in data:
        if as_lower_str("assistant_autonomy_level") not in ASSISTANT_AUTONOMY_VALUES:
            errors["assistant_autonomy_level"] = f"assistant_autonomy_level must be one of {sorted(ASSISTANT_AUTONOMY_VALUES)}"

    if "default_meeting_duration" in data:
        val = data.get("default_meeting_duration")
        if not isinstance(val, int) or val not in (30, 45, 60):
            errors["default_meeting_duration"] = "default_meeting_duration must be 30, 45, or 60"

    if "default_meeting_platform" in data:
        if as_lower_str("default_meeting_platform") not in PLATFORM_VALUES:
            errors["default_meeting_platform"] = f"default_meeting_platform must be one of {sorted(PLATFORM_VALUES)}"

    if "working_hours_start" in data:
        val = data.get("working_hours_start")
        if not isinstance(val, str) or len(val) != 5 or ":" not in val:
            errors["working_hours_start"] = "working_hours_start must be HH:MM"

    if "working_hours_end" in data:
        val = data.get("working_hours_end")
        if not isinstance(val, str) or len(val) != 5 or ":" not in val:
            errors["working_hours_end"] = "working_hours_end must be HH:MM"

    if "working_hours_start" in data and "working_hours_end" in data:
        if data["working_hours_start"] >= data["working_hours_end"]:
            errors["working_hours"] = "working_hours_end must be later than working_hours_start"

    if "working_days" in data:
        val = data.get("working_days")
        if not isinstance(val, list) or any(day not in WEEK_DAY_VALUES for day in val):
            errors["working_days"] = "working_days must be an array of Mon-Sun values"

    if "buffer_time_minutes" in data:
        val = data.get("buffer_time_minutes")
        if not isinstance(val, int) or val < 0 or val > 180:
            errors["buffer_time_minutes"] = "buffer_time_minutes must be between 0 and 180"

    if "trusted_contacts" in data:
        val = data.get("trusted_contacts")
        if not isinstance(val, list) or any(not isinstance(item, str) or not item.strip() for item in val):
            errors["trusted_contacts"] = "trusted_contacts must be a string list"

    bool_fields = [
        "daily_briefing_enabled",
        "auto_followups_enabled",
        "prevent_past_dates",
        "prevent_outside_working_hours",
        "require_schedule_confirmation",
        "email_auto_categorize",
        "email_draft_suggestions",
        "require_email_approval",
        "notifications_enabled",
        "email_notifications_enabled",
    ]
    for field in bool_fields:
        if field in data and not isinstance(data.get(field), bool):
            errors[field] = f"{field} must be boolean"

    if "timezone" in data and not is_valid_timezone(data.get("timezone")):
        errors["timezone"] = "timezone is invalid"

    if "language" in data:
        if as_lower_str("language") not in LANGUAGE_VALUES:
            errors["language"] = f"language must be one of {sorted(LANGUAGE_VALUES)}"

    return errors


def update_user_settings(user_id, payload):
    settings = get_or_create_user_settings(user_id)
    errors = validate_settings_update(payload)
    if errors:
        return None, errors

    before = settings.to_dict()
    normalized_payload = dict(payload)
    normalize_keys = {
        "theme_mode",
        "assistant_tone",
        "assistant_response_length",
        "assistant_autonomy_level",
        "default_meeting_platform",
        "language",
    }
    for key in normalize_keys:
        if key in normalized_payload and isinstance(normalized_payload[key], str):
            normalized_payload[key] = normalized_payload[key].strip().lower()

    for key, value in normalized_payload.items():
        if key == "trusted_contacts" and isinstance(value, list):
            value = sorted({
                str(item).strip().lower()
                for item in value
                if isinstance(item, str) and item.strip()
            })
        if hasattr(settings, key):
            setattr(settings, key, value)

    db.session.commit()

    after = settings.to_dict()
    changes = {}
    for key, value in after.items():
        if key in ("id", "user_id", "created_at", "updated_at"):
            continue
        if before.get(key) != value:
            changes[key] = {"before": before.get(key), "after": value}

    if changes:
        log_settings_change(user_id, changes)

    return after, None
