from flask import current_app, jsonify, request, Response
from marshmallow import fields, validate

from app.extensions import limiter
from app.routes.public.routes import _payload, api_errors
from app.schemas.survey import StrictSchema, SubmissionSchema
from app.services.challenge_service import create_challenge
from app.services.simulation_service import (
    SIMULATION_COOKIE, SIMULATION_COOKIE_PATH, SIMULATION_TTL,
    active_simulation, simulation_login, simulation_csv, revoke_simulation_session,
)
from app.services.survey_errors import SurveyError
from app.utils.security import digest
from app.utils.time import utcnow
from . import simulation_bp


class SimulationLoginSchema(StrictSchema):
    email = fields.Email(required=True, validate=validate.Length(max=255))
    password = fields.String(required=True, validate=validate.Length(min=1, max=128))


class SimulationRunSchema(StrictSchema):
    runId = fields.String(required=True, validate=validate.Regexp(r'^[A-Za-z0-9_-]{43}$'))


class SimulationSubmissionSchema(SubmissionSchema):
    runId = fields.String(required=True, validate=validate.Regexp(r'^[A-Za-z0-9_-]{43}$'))

    class Meta(SubmissionSchema.Meta):
        exclude = ('token', 'deviceId')


def login_key():
    data = request.get_json(silent=True)
    email = data.get('email', '') if isinstance(data, dict) else ''
    return 'simulation-account:' + digest(str(email).strip().lower()[:255])


@simulation_bp.get('/session')
@limiter.limit('120 per minute')
@api_errors
def status():
    try:
        return jsonify(active_simulation().status)
    except SurveyError as exc:
        if exc.code in ('simulation_disabled', 'simulation_login_required', 'simulation_restarted'):
            return jsonify(status='disabled' if exc.code == 'simulation_disabled' else 'unauthenticated', message=exc.message)
        raise


@simulation_bp.post('/login')
@limiter.limit('5 per minute')
@limiter.limit('10 per hour', key_func=login_key)
@api_errors
def login():
    data = _payload(SimulationLoginSchema())
    result, token = simulation_login(data['email'], data['password'])
    response = jsonify(result)
    response.set_cookie(SIMULATION_COOKIE, token, max_age=SIMULATION_TTL,
                        httponly=True, secure=current_app.config['SESSION_COOKIE_SECURE'],
                        samesite='Strict', path=SIMULATION_COOKIE_PATH)
    return response


@simulation_bp.post('/logout')
@api_errors
def logout():
    revoke_simulation_session()
    response = jsonify(status='unauthenticated')
    response.delete_cookie(SIMULATION_COOKIE, path=SIMULATION_COOKIE_PATH, samesite='Strict',
                           secure=current_app.config['SESSION_COOKIE_SECURE'], httponly=True)
    return response


@simulation_bp.post('/challenge')
@limiter.limit('60 per minute')
@api_errors
def challenge():
    data = _payload(SimulationRunSchema())
    return jsonify(create_challenge(active_simulation(data['runId'])))


@simulation_bp.post('/export.csv')
@limiter.limit('60 per hour')
@api_errors
def export_csv():
    # Authenticate before accepting any answers, including direct API attempts.
    invitation = active_simulation()
    data = _payload(SimulationSubmissionSchema())
    active_simulation(data['runId'])
    return Response(simulation_csv(data, invitation), content_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="simulacion_{utcnow():%Y%m%d_%H%M%S}.csv"',
        'X-Content-Type-Options': 'nosniff',
    })
