from functools import wraps

from flask import current_app, jsonify, request
from marshmallow import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db, limiter
from app.schemas.survey import LinkSchema, SessionSchema, SubmissionSchema
from app.services.survey_errors import SurveyError
from app.services.survey_service import BROWSER_COOKIE, create_link, session_status, owned_invitation, submit_response
from app.services.challenge_service import create_challenge
from . import public_bp


def _payload(schema):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError({'_schema': ['Se esperaba un objeto JSON.']})
    return schema.load(data)


def api_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValidationError as exc:
            db.session.rollback()
            return jsonify(error='Revisá los datos de la encuesta.', code='validation_error', details=exc.messages), 422
        except SurveyError as exc:
            db.session.rollback()
            return jsonify(error=exc.message, code=exc.code), exc.status
        except SQLAlchemyError:
            db.session.rollback()
            # Never include the DB exception: bound parameters contain opinions.
            current_app.logger.error('survey_database_unavailable')
            return jsonify(error='No se pudo guardar la encuesta. Tus respuestas siguen en este navegador.', code='service_unavailable'), 503
    return wrapped


@public_bp.after_request
def private_api_headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@public_bp.post('/api/survey/links')
@limiter.limit(lambda: current_app.config['SURVEY_LINK_IP_LIMIT'])
@api_errors
def links():
    result, cookie = create_link(_payload(LinkSchema()))
    response = jsonify(result)
    if cookie:
        response.set_cookie(BROWSER_COOKIE, cookie, max_age=365 * 86400,
                            httponly=True, secure=current_app.config.get('SURVEY_COOKIE_SECURE', True),
                            samesite='Lax', path='/')
    return response, 201


@public_bp.post('/api/survey/session')
@limiter.limit('60 per minute')
@api_errors
def survey_session():
    return jsonify(session_status(_payload(SessionSchema())))


@public_bp.post('/api/survey/challenge')
@limiter.limit(lambda: current_app.config['SURVEY_CHALLENGE_IP_LIMIT'])
@api_errors
def survey_challenge():
    invitation = owned_invitation(_payload(SessionSchema()))
    return jsonify(create_challenge(invitation))


@public_bp.post('/api/survey/responses')
@limiter.limit(lambda: current_app.config['SURVEY_RESPONSE_IP_LIMIT'])
@api_errors
def responses():
    result, status = submit_response(_payload(SubmissionSchema()))
    return jsonify(result), status
