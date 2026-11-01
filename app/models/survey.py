"""Survey opinions with connection IPs and detached anti-duplication evidence.

Phone/device duplicate identifiers are survey-scoped HMACs. The response IP
is recorded separately on its opinion row; invitation receipts stay independent.
"""
from datetime import datetime, timezone
from uuid import uuid4

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SurveyInvitation(db.Model):
    __tablename__ = 'survey_invitations'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    survey_id = db.Column(db.String(64), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    device_hash = db.Column(db.String(64), nullable=False)
    browser_hash = db.Column(db.String(64), nullable=False)
    ip_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    consumed_at = db.Column(db.DateTime)
    receipt_id = db.Column(db.String(36))
    submission_hash = db.Column(db.String(64))
    attribution = db.Column(db.JSON, nullable=False, default=dict)


class ParticipantIdentity(db.Model):
    """Durable unique claims; never exported or related to opinion rows."""
    __tablename__ = 'participant_identities'
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    digest = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (
        db.UniqueConstraint('survey_id', 'kind', 'digest', name='uq_participant_identity'),
    )


class SurveyResponse(db.Model):
    __tablename__ = 'survey_responses'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    survey_id = db.Column(db.String(64), nullable=False, index=True)
    answers = db.Column(db.JSON, nullable=False)
    # NULL is reserved for historical responses collected before IP recording.
    ip_address = db.Column(db.String(45), nullable=True)
    device_metadata = db.Column(db.JSON, nullable=True)
    device_type = db.Column(db.String(16), nullable=True)
    os_family = db.Column(db.String(24), nullable=True)
    browser_family = db.Column(db.String(24), nullable=True)
    browser_context = db.Column(db.String(24), nullable=True)
    consent_version = db.Column(db.String(32), nullable=False)
    consented_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    __table_args__ = (
        db.Index('ix_response_device_type', 'survey_id', 'device_type'),
        db.Index('ix_response_os_family', 'survey_id', 'os_family'),
        db.Index('ix_response_browser_family', 'survey_id', 'browser_family'),
        db.Index('ix_response_browser_context', 'survey_id', 'browser_context'),
    )


class ResponseValue(db.Model):
    """Indexed categorical answer projection for portable SQL analytics."""
    __tablename__ = 'response_values'
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.String(36), db.ForeignKey('survey_responses.id', ondelete='CASCADE'), nullable=False)
    variable = db.Column(db.String(80), nullable=False)
    value = db.Column(db.String(80), nullable=False)
    __table_args__ = (
        db.UniqueConstraint('response_id', 'variable', 'value', name='uq_response_value'),
        db.Index('ix_response_value_filter', 'variable', 'value', 'response_id'),
    )
