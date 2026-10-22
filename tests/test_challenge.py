import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app import create_app
from app.extensions import db
from app.models.survey import ParticipantIdentity, SurveyInvitation, SurveyResponse
from app.schemas.catalog import AREAS
from app.services.challenge_service import consume_challenge
from app.services.survey_errors import SurveyError


@pytest.fixture
def app():
    instance = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis()})
    with instance.app_context():
        db.create_all()
    yield instance
    with instance.app_context():
        db.session.remove()
        db.drop_all()


def begin(client):
    device = str(uuid4())
    response = client.post('/api/survey/links', json={'deviceId': device})
    assert response.status_code == 201
    return {'token': response.json['token'], 'deviceId': device}


def verifier(client, invitation):
    response = client.post('/api/survey/challenge', json=invitation)
    assert response.status_code == 200, response.json
    parts = re.findall(r'[0-9]+', response.json['question'])
    assert len(parts) == 2
    assert all(12 <= int(value) <= 49 for value in parts)
    return {'challengeId': response.json['challengeId'], 'challengeAnswer': str(sum(map(int, parts)))}


def payload(invitation, challenge):
    return {
        **invitation, **challenge, 'website': '', 'phone': '099123456', 'consent': True, 'consentVersion': '2026-01',
        'answers': {
            'adult': 'si', 'lavallejaResident': 'si', 'locality': 'minas',
            'gender': 'ns_nc', 'ageRange': '35_44', 'voted2025': 'pnr',
            'generalEvaluation': 'buena', 'generalSatisfaction': 'conforme', 'managementEvolution': 'aprox_igual',
            'areas': {key: 'ns_nc' for key in AREAS}, 'concerns': ['ns_nc'], 'priorities': ['ns_nc'],
            'openComment': 'Comentario para una prueba de seguridad.',
        },
    }


def test_numerical_verifier_required_and_single_use_with_idempotent_retry(app):
    client = app.test_client()
    invitation = begin(client)
    verified = verifier(client, invitation)
    data = payload(invitation, verified)
    first = client.post('/api/survey/responses', json=data)
    assert first.status_code == 201
    # The saved response is returned even after Redis proof expiry or a client
    # losing its original verifier. The opinion/phone content must be identical.
    app.extensions['redis'].flushdb()
    repeated = client.post('/api/survey/responses', json={**data, 'challengeId': str(uuid4()), 'challengeAnswer': '0'})
    assert repeated.status_code == 200 and repeated.json == first.json
    with app.app_context():
        assert SurveyResponse.query.count() == 1
        assert ParticipantIdentity.query.filter_by(kind='phone').count() == 1


def test_no_sms_service_or_phone_verification_fields_remain(app):
    client = app.test_client()
    assert client.post('/api/survey/phone/start', json={}).status_code == 404
    assert client.post('/api/survey/phone/verify', json={}).status_code == 404
    assert not any('phone' in field for field in SurveyInvitation.__table__.columns.keys())
    invitation = begin(client)
    data = payload(invitation, verifier(client, invitation))
    assert client.post('/api/survey/responses', json=data).status_code == 201


def test_wrong_answers_exhaust_attempts_without_saving_opinion(app):
    client = app.test_client()
    invitation = begin(client)
    verified = verifier(client, invitation)
    data = payload(invitation, verified)
    for attempt in range(5):
        response = client.post('/api/survey/responses', json={**data, 'challengeAnswer': '0'})
        assert response.status_code == 400
        assert response.json['code'] == ('challenge_exhausted' if attempt == 4 else 'challenge_invalid')
    exhausted = client.post('/api/survey/responses', json=data)
    assert exhausted.json['code'] == 'challenge_exhausted'
    with app.app_context():
        assert SurveyResponse.query.count() == 0
    replacement = payload(invitation, verifier(client, invitation))
    assert client.post('/api/survey/responses', json=replacement).status_code == 201


def test_expired_and_replaced_verifier_cannot_be_used(app):
    client = app.test_client()
    invitation = begin(client)
    old = verifier(client, invitation)
    newest = verifier(client, invitation)
    outdated = client.post('/api/survey/responses', json=payload(invitation, old))
    assert outdated.status_code == 400 and outdated.json['code'] == 'challenge_invalid'
    for key in app.extensions['redis'].scan_iter('survey:challenge:*'):
        app.extensions['redis'].expire(key, 0)
    expired = client.post('/api/survey/responses', json=payload(invitation, newest))
    assert expired.status_code == 400 and expired.json['code'] == 'challenge_expired'


def test_verifier_is_bound_to_invitation_browser_and_device(app):
    first, other = app.test_client(), app.test_client()
    invitation, second = begin(first), begin(other)
    original = verifier(first, invitation)
    assert other.post('/api/survey/challenge', json=invitation).status_code == 403
    forged = other.post('/api/survey/responses', json=payload(second, original))
    assert forged.status_code == 400 and forged.json['code'] == 'challenge_invalid'
    assert first.post('/api/survey/responses', json=payload(invitation, original)).status_code == 201


def test_bad_form_and_honeypot_do_not_consume_verifier(app):
    client = app.test_client()
    invitation = begin(client)
    data = payload(invitation, verifier(client, invitation))
    malformed = {**data, 'answers': {**data['answers'], 'gender': 'forged'}}
    assert client.post('/api/survey/responses', json=malformed).status_code == 422
    trapped = client.post('/api/survey/responses', json={**data, 'website': 'https://spam.example/'})
    assert trapped.status_code == 400 and trapped.json['code'] == 'submission_rejected'
    assert client.post('/api/survey/responses', json=data).status_code == 201


@pytest.mark.parametrize('answer', [42, True, None, '', 'x', '12345', '٣٢'])
def test_verifier_answer_requires_bounded_ascii_numeric_string(app, answer):
    client = app.test_client()
    invitation = begin(client)
    data = payload(invitation, verifier(client, invitation))
    result = client.post('/api/survey/responses', json={**data, 'challengeAnswer': answer})
    assert result.status_code == 422


def test_minimum_fill_time_is_enforced_before_consumption(app):
    app.config['SURVEY_MIN_FILL_SECONDS'] = 15
    client = app.test_client()
    invitation = begin(client)
    data = payload(invitation, verifier(client, invitation))
    early = client.post('/api/survey/responses', json=data)
    assert early.status_code == 429 and early.json['code'] == 'submission_too_fast'
    with app.app_context():
        SurveyInvitation.query.one().created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=16)
        db.session.commit()
    assert client.post('/api/survey/responses', json=data).status_code == 201


def test_redis_outage_fails_closed_without_saving(app, monkeypatch):
    client = app.test_client()
    invitation = begin(client)
    data = payload(invitation, verifier(client, invitation))
    monkeypatch.setattr(app.extensions['redis'], 'pipeline', Mock(side_effect=RedisConnectionError()))
    assert client.post('/api/survey/responses', json=data).status_code == 503
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_database_failure_requires_fresh_verifier_and_preserves_invitation(app, monkeypatch):
    client = app.test_client()
    invitation = begin(client)
    data = payload(invitation, verifier(client, invitation))
    with monkeypatch.context() as context:
        context.setattr(db.session, 'commit', Mock(side_effect=OperationalError('commit', {}, Exception('unavailable'))))
        assert client.post('/api/survey/responses', json=data).status_code == 503
    with app.app_context():
        assert SurveyInvitation.query.one().consumed_at is None
        assert SurveyResponse.query.count() == 0
    old = client.post('/api/survey/responses', json=data)
    assert old.status_code == 409 and old.json['code'] == 'challenge_used'
    fresh = payload(invitation, verifier(client, invitation))
    assert client.post('/api/survey/responses', json=fresh).status_code == 201


def test_redis_proof_consumption_is_atomic_across_workers(app):
    client = app.test_client()
    invitation = begin(client)
    verified = verifier(client, invitation)
    with app.app_context():
        row = SurveyInvitation.query.one()
        # Eagerly loaded scalar values remain usable after the session closes.
        snapshot = type('InvitationBinding', (), {
            'token_hash': row.token_hash, 'device_hash': row.device_hash, 'browser_hash': row.browser_hash,
        })()

    def compete(_):
        with app.app_context():
            try:
                consume_challenge(snapshot, verified['challengeId'], verified['challengeAnswer'])
                return 'accepted'
            except SurveyError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(compete, range(8)))
    assert results.count('accepted') == 1
    assert all(result in ('accepted', 'challenge_used') for result in results)
