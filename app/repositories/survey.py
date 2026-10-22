from flask import current_app
from sqlalchemy import or_, and_

from app.extensions import db
from app.models.survey import ParticipantIdentity, ResponseValue, SurveyInvitation
from app.schemas.catalog import VARIABLE_DEFINITIONS, value_at


def invitation_by_hash(token_hash, lock=False):
    query = SurveyInvitation.query.filter_by(survey_id=current_app.config['SURVEY_ID'], token_hash=token_hash)
    if lock:
        query = query.with_for_update()
    return query.first()


def has_claims(claims):
    if not claims:
        return False
    condition = or_(*(and_(ParticipantIdentity.kind == kind, ParticipantIdentity.digest == digest)
                      for kind, digest in claims.items()))
    return db.session.query(ParticipantIdentity.id).filter(
        ParticipantIdentity.survey_id == current_app.config['SURVEY_ID'], condition,
    ).first() is not None


def add_claims(claims):
    # UNIQUE(survey_id, kind, digest) is the final authority across workers.
    for kind, digest in sorted(claims.items()):
        db.session.add(ParticipantIdentity(survey_id=current_app.config['SURVEY_ID'], kind=kind, digest=digest))


def add_values(response):
    for key in VARIABLE_DEFINITIONS:
        value = value_at(response.answers, key)
        values = value if isinstance(value, list) else [value]
        for answer in values:
            if answer is not None:
                db.session.add(ResponseValue(response_id=response.id, variable=key, value=answer))
