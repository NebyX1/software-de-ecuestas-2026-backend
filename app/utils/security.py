import hashlib
import hmac
from flask import current_app, request
from flask_login import current_user
from app.extensions import db
from app.models.audit import ActivityLog


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def log_activity(action, details='', user=None):
    user = user or (current_user if current_user.is_authenticated else None)
    ip_hash = hmac.new(current_app.config['IDENTITY_HMAC_KEY'].encode(), (request.remote_addr or '').encode(), hashlib.sha256).hexdigest()
    db.session.add(ActivityLog(user_id=user.id if user else None, username=user.username if user else None, action=action, details=details[:500], ip_hash=ip_hash))


def csv_safe(value):
    value = '' if value is None else str(value)
    if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        return "'" + value
    return value
