"""Revocable simulation access. Redis holds controls, never survey answers."""
import csv
import io
import json
import secrets
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from flask import current_app, request

from app.extensions import db
from app.models.user import User
from app.schemas.survey import normalize_phone
from app.services.analytics_service import csv_columns, csv_record
from app.services.challenge_service import consume_challenge
from app.services.device_metadata import capture_device_metadata
from app.services.survey_errors import SurveyError
from app.utils.security import digest
from app.utils.time import utcnow

SIMULATION_COOKIE = 'survey_simulation'
SIMULATION_COOKIE_PATH = '/api/simulation'
SIMULATION_TTL = 4 * 3600


def _control_key():
    return 'simulation:control:' + digest(current_app.config['SURVEY_ID'])


def _session_key(token):
    return 'simulation:session:' + digest(token)


def simulation_generation():
    value = current_app.extensions['redis'].get(_control_key())
    return value.decode('ascii') if isinstance(value, bytes) else value


def enable_simulation(*, restart=False):
    redis = current_app.extensions['redis']
    # NX makes repeated enables harmless; restart deliberately revokes all runs.
    redis.set(_control_key(), secrets.token_urlsafe(32), nx=not restart)


def disable_simulation():
    current_app.extensions['redis'].delete(_control_key())


def require_enabled():
    generation = simulation_generation()
    if not generation:
        raise SurveyError('simulation_disabled', 'La simulación está deshabilitada. Habilitala desde el panel de administración.', 403)
    return generation


def simulation_login(email, password):
    generation = require_enabled()
    user = db.session.scalar(db.select(User).where(User.email == email.strip().lower()))
    if not user:
        from app.models.user import ph
        ph.hash(password)
    if not user or not user.is_active or not user.check_password(password):
        raise SurveyError('simulation_credentials', 'Correo o contraseña de administrador inválidos.', 401)
    revoke_simulation_session()
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(seconds=SIMULATION_TTL)
    payload = {'user_id': user.id, 'auth_version': user.auth_version,
               'generation': generation, 'expires_at': expires.isoformat() + 'Z'}
    current_app.extensions['redis'].set(_session_key(token), json.dumps(payload), ex=SIMULATION_TTL)
    return {'status': 'active', 'runId': generation, 'expiresAt': payload['expires_at'], 'username': user.username}, token


def revoke_simulation_session():
    token = request.cookies.get(SIMULATION_COOKIE, '')
    if len(token) == 43:
        current_app.extensions['redis'].delete(_session_key(token))


def active_simulation(run_id=None):
    generation = require_enabled()
    token = request.cookies.get(SIMULATION_COOKIE, '')
    raw = current_app.extensions['redis'].get(_session_key(token)) if len(token) == 43 else None
    if not raw:
        raise SurveyError('simulation_login_required', 'Ingresá con correo y contraseña de administrador para probar el formulario.', 401)
    payload = json.loads(raw)
    if payload['generation'] != generation or (run_id is not None and run_id != generation):
        raise SurveyError('simulation_restarted', 'La simulación fue reiniciada. Ingresá nuevamente para comenzar otra prueba.', 401)
    user = db.session.get(User, payload['user_id'])
    if not user or not user.is_active or user.auth_version != payload['auth_version']:
        raise SurveyError('simulation_login_required', 'El acceso de prueba venció. Ingresá nuevamente.', 401)
    return SimpleNamespace(
        namespace='simulation', token_hash=digest('simulation:' + token + ':' + generation),
        device_hash=digest('simulation-device:' + token), browser_hash=digest('simulation-browser:' + token),
        expires_at=utcnow() + timedelta(seconds=max(1, current_app.extensions['redis'].ttl(_session_key(token)))),
        status={'status': 'active', 'runId': generation, 'expiresAt': payload['expires_at'], 'username': user.username},
    )


def simulation_csv(data, invitation):
    # This path never calls the production invitation, identity or submission services.
    normalize_phone(data['phone'])  # Exercise the same phone-format rule; discard it.
    if data.get('website'):
        raise SurveyError('submission_rejected', 'No pudimos validar el envío. Revisá el formulario e intentá nuevamente.', 400)
    consume_challenge(invitation, data['challengeId'], data['challengeAnswer'])
    response = SimpleNamespace(
        id='SIMULACION-' + str(uuid4()), created_at=utcnow(), answers=data['answers'],
        consent_version=data['consentVersion'],
        device_metadata=capture_device_metadata(request.headers.get('User-Agent', ''), data.get('clientMetadata', {})),
    )
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(csv_columns())
    writer.writerow(csv_record(response))
    return '\ufeff' + output.getvalue()
