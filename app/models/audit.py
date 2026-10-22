from app.extensions import db
from app.utils.time import utcnow


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    username = db.Column(db.String(64))
    action = db.Column(db.String(64), nullable=False, index=True)
    details = db.Column(db.String(500), nullable=False, default='')
    ip_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
