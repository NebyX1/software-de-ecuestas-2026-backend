from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from flask_login import UserMixin
from app.extensions import db
from app.utils.time import utcnow

ph = PasswordHasher()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_superuser = db.Column(db.Boolean, nullable=False, default=False)
    auth_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = ph.hash(password)

    def check_password(self, password):
        try:
            valid = ph.verify(self.password_hash, password)
            if valid and ph.check_needs_rehash(self.password_hash):
                self.password_hash = ph.hash(password)
            return valid
        except (VerificationError, InvalidHashError):
            return False


class TwoFactorCode(db.Model):
    __tablename__ = 'two_factor_codes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    challenge_hash = db.Column(db.String(64), nullable=False, unique=True)
    auth_version = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def __init__(self, user_id, code, challenge_hash, auth_version, ttl=600):
        self.user_id = user_id
        self.code_hash = ph.hash(code)
        self.challenge_hash = challenge_hash
        self.auth_version = auth_version
        self.expires_at = utcnow() + timedelta(seconds=ttl)

    def verify_code(self, code):
        try:
            return ph.verify(self.code_hash, code)
        except (VerificationError, InvalidHashError):
            return False
