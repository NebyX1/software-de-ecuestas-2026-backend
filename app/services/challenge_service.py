"""Self-contained numerical verifier backed by Redis, with atomic single use.

This accessible addition challenge is a basic friction mechanism, not proof
that a respondent is a unique person or that sophisticated automation is absent.
No expected answer, phone or opinion is sent to an external provider.
"""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import current_app
from redis.exceptions import WatchError

from .survey_errors import SurveyError


def _hash(kind, value):
    key = current_app.config['IDENTITY_HMAC_KEY'].encode()
    message = f"{current_app.config['SURVEY_ID']}\0{kind}\0{value}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _challenge_key(challenge_id, namespace='survey'):
    return namespace + ':challenge:' + _hash('challenge-key', challenge_id)


def _active_key(invitation):
    return getattr(invitation, 'namespace', 'survey') + ':challenge-active:' + invitation.token_hash


def _binding(invitation):
    return _hash('challenge-binding', ':'.join((invitation.token_hash, invitation.device_hash, invitation.browser_hash)))


def create_challenge(invitation):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ttl = min(current_app.config.get('SURVEY_CHALLENGE_TTL_SECONDS', 300),
              max(1, int((invitation.expires_at - now).total_seconds())))
    first, second = secrets.randbelow(38) + 12, secrets.randbelow(38) + 12
    challenge_id = str(uuid4())
    payload = {
        'binding': _binding(invitation),
        'answer_hash': _hash('challenge-answer', f'{challenge_id}:{first + second}'),
        'attempts': 0, 'used': False,
    }
    redis = current_app.extensions['redis']
    # A new verifier invalidates the previous one for this invitation. Both
    # records expire automatically; no permanent fingerprint is kept in Redis.
    with redis.pipeline(transaction=True) as transaction:
        transaction.set(_challenge_key(challenge_id, getattr(invitation, 'namespace', 'survey')), json.dumps(payload), ex=ttl)
        transaction.set(_active_key(invitation), challenge_id, ex=ttl)
        transaction.execute()
    return {'challengeId': challenge_id, 'question': f'¿Cuánto es {first} + {second}?',
            'expiresAt': (now + timedelta(seconds=ttl)).isoformat() + 'Z'}


def consume_challenge(invitation, challenge_id, answer):
    redis = current_app.extensions['redis']
    key, active_key = _challenge_key(challenge_id, getattr(invitation, 'namespace', 'survey')), _active_key(invitation)
    expected_binding = _binding(invitation)
    expected_answer = _hash('challenge-answer', f'{challenge_id}:{int(answer)}')
    max_attempts = current_app.config.get('SURVEY_CHALLENGE_MAX_ATTEMPTS', 5)
    for _ in range(8):
        try:
            with redis.pipeline() as transaction:
                transaction.watch(key, active_key)
                raw = transaction.get(key)
                if not raw:
                    raise SurveyError('challenge_expired', 'La verificación venció. Solicitá una nueva.', 400)
                try:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError()
                    bound = payload.get('binding', '')
                    answer_hash = payload.get('answer_hash', '')
                    attempts = payload.get('attempts')
                    if (not isinstance(bound, str) or not isinstance(answer_hash, str)
                            or not isinstance(attempts, int)):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise SurveyError('service_unavailable', 'No se pudo validar la seguridad. Solicitá otra verificación.', 503)
                if not hmac.compare_digest(bound, expected_binding):
                    raise SurveyError('challenge_invalid', 'La verificación no corresponde a este enlace.', 400)
                if payload.get('used'):
                    raise SurveyError('challenge_used', 'La verificación ya fue utilizada. Solicitá una nueva.', 409)
                if attempts >= max_attempts:
                    raise SurveyError('challenge_exhausted', 'Se agotaron los intentos. Solicitá una nueva verificación.', 400)
                active = transaction.get(active_key)
                if isinstance(active, bytes):
                    active = active.decode('ascii')
                if active != challenge_id:
                    raise SurveyError('challenge_invalid', 'La verificación cambió. Respondé la nueva pregunta.', 400)
                valid = hmac.compare_digest(answer_hash, expected_answer)
                payload['attempts'] = attempts + 1
                payload['used'] = valid
                transaction.multi()
                transaction.set(key, json.dumps(payload), keepttl=True)
                if valid:
                    transaction.delete(active_key)
                transaction.execute()
                if not valid:
                    code = 'challenge_exhausted' if payload['attempts'] >= max_attempts else 'challenge_invalid'
                    raise SurveyError(code, 'La respuesta de seguridad no es correcta. Revisala o solicitá otra.', 400)
                return
        except WatchError:
            continue
    raise SurveyError('submission_busy', 'La verificación está en uso. Intentá nuevamente.', 409)
