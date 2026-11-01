"""The fast entry result requires an actual authenticated-cookie round trip."""
from datetime import timedelta
from uuid import uuid4

import fakeredis
import pytest

from app import create_app
from app.extensions import db
from app.models.survey import ParticipantIdentity, ResponseValue, SurveyInvitation, SurveyResponse
from app.services.survey_service import BROWSER_COOKIE, digest, utcnow


API = 'https://api.example.test'
FRONTEND = 'https://survey.example.test'


@pytest.fixture
def entry_app():
    app = create_app('testing', {
        'REDIS_CLIENT': fakeredis.FakeRedis(), 'WTF_CSRF_ENABLED': True,
        'SESSION_COOKIE_SECURE': True, 'SURVEY_COOKIE_SECURE': True,
        'FRONTEND_URL': FRONTEND, 'CORS_ALLOWED_ORIGINS': [FRONTEND],
    })
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def csrf(client, *, entry=False):
    return client.get('/api/csrf' + ('?entry=survey' if entry else ''),
                      base_url=API, headers={'Origin': FRONTEND})


def post(client, path, data, proof):
    return client.post(path, json=data, base_url=API, headers={
        'Origin': FRONTEND, 'Referer': FRONTEND + '/', 'X-CSRFToken': proof})


def counts(app):
    with app.app_context():
        return tuple(db.session.query(model).count() for model in
                     (SurveyInvitation, ParticipantIdentity, SurveyResponse, ResponseValue))


def test_entry_configuration_sets_hardened_cookie_without_creating_survey_data(entry_app):
    client = entry_app.test_client()
    before = counts(entry_app)
    configuration = csrf(client, entry=True)
    assert configuration.status_code == 200
    cookie = client.get_cookie(BROWSER_COOKIE, domain='api.example.test')
    assert cookie and cookie.secure and cookie.http_only and cookie.same_site == 'Lax'
    assert cookie.path == '/' and cookie.max_age == 365 * 86400
    assert configuration.headers['Access-Control-Allow-Origin'] == FRONTEND
    assert configuration.headers['Access-Control-Allow-Credentials'] == 'true'
    assert 'no-store' in configuration.headers['Cache-Control']
    assert cookie.value not in configuration.get_data(as_text=True)
    assert counts(entry_app) == before
    second = csrf(client, entry=True)
    assert client.get_cookie(BROWSER_COOKIE, domain='api.example.test').value == cookie.value
    assert not any(value.startswith(BROWSER_COOKIE + '=') for value in second.headers.getlist('Set-Cookie'))


def test_entry_changes_preserve_existing_mail_diagnostic_command(entry_app):
    result = entry_app.test_cli_runner().invoke(args=['check-mail', '--help'])
    assert result.exit_code == 0 and 'check-mail' in result.output


@pytest.mark.parametrize('query', ['', '?entry=admin', '?entry=simulation', '?entry=other'])
def test_non_survey_csrf_does_not_create_browser_identity(entry_app, query):
    client = entry_app.test_client()
    result = client.get('/api/csrf' + query, base_url=API)
    assert result.status_code == 200
    assert client.get_cookie(BROWSER_COOKIE, domain='api.example.test') is None
    assert counts(entry_app) == (0, 0, 0, 0)


def test_link_returns_active_session_only_after_real_cookie_round_trip(entry_app):
    owner = entry_app.test_client()
    configuration = csrf(owner, entry=True)
    device = str(uuid4())
    linked = post(owner, '/api/survey/links', {'deviceId': device}, configuration.json['csrf_token'])
    assert linked.status_code == 201
    assert linked.json['session'] == {'status': 'active', 'expiresAt': linked.json['expiresAt']}
    assert set(linked.json) == {'token', 'expiresAt', 'session'}
    assert counts(entry_app) == (1, 0, 0, 0)
    status = post(owner, '/api/survey/session', {'token': linked.json['token'], 'deviceId': device},
                  configuration.json['csrf_token'])
    assert status.status_code == 200 and status.json == linked.json['session']


@pytest.mark.parametrize('invalid_cookie', [False, True])
def test_new_or_invalid_browser_cookie_keeps_separate_validation_fallback(entry_app, invalid_cookie):
    client = entry_app.test_client()
    proof = csrf(client).json['csrf_token']
    if invalid_cookie:
        client.set_cookie(BROWSER_COOKIE, 'invalid-cookie', domain='api.example.test')
    device = str(uuid4())
    linked = post(client, '/api/survey/links', {'deviceId': device}, proof)
    assert linked.status_code == 201
    assert 'session' not in linked.json
    assert any(value.startswith(BROWSER_COOKIE + '=') for value in linked.headers.getlist('Set-Cookie'))
    validated = post(client, '/api/survey/session', {'token': linked.json['token'], 'deviceId': device}, proof)
    assert validated.status_code == 200 and validated.json['status'] == 'active'


@pytest.mark.parametrize('proof', ['', 'invalid-csrf'])
def test_primed_browser_does_not_bypass_csrf(entry_app, proof):
    client = entry_app.test_client()
    csrf(client, entry=True)
    rejected = post(client, '/api/survey/links', {'deviceId': str(uuid4())}, proof)
    assert rejected.status_code == 400 and rejected.json['code'] == 'csrf_invalid'
    assert counts(entry_app) == (0, 0, 0, 0)


def test_copying_fast_entry_token_and_device_does_not_authorize_another_browser(entry_app):
    owner, stranger = entry_app.test_client(), entry_app.test_client()
    owner_proof = csrf(owner, entry=True).json['csrf_token']
    device = str(uuid4())
    linked = post(owner, '/api/survey/links', {'deviceId': device}, owner_proof)
    assert linked.json['session']['status'] == 'active'
    stranger_proof = csrf(stranger, entry=True).json['csrf_token']
    rejected = post(stranger, '/api/survey/session', {'token': linked.json['token'], 'deviceId': device}, stranger_proof)
    assert rejected.status_code == 403 and rejected.json['code'] == 'link_bound'
    assert counts(entry_app) == (1, 0, 0, 0)


def test_primed_browser_still_checks_durable_duplicate_claims(entry_app):
    client = entry_app.test_client()
    proof = csrf(client, entry=True).json['csrf_token']
    device = str(uuid4())
    with entry_app.app_context():
        db.session.add(ParticipantIdentity(survey_id=entry_app.config['SURVEY_ID'],
                                          kind='device', digest=digest('device', device)))
        db.session.commit()
    rejected = post(client, '/api/survey/links', {'deviceId': device}, proof)
    assert rejected.status_code == 409 and rejected.json['code'] == 'duplicate_response'
    assert counts(entry_app) == (0, 1, 0, 0)


def test_primed_browser_does_not_bypass_required_turnstile(entry_app):
    entry_app.config.update(TURNSTILE_REQUIRED=True, TURNSTILE_SITE_KEY='test-public-sitekey')
    client = entry_app.test_client()
    configuration = csrf(client, entry=True)
    assert configuration.json['turnstileSiteKey'] == 'test-public-sitekey'
    rejected = post(client, '/api/survey/links', {'deviceId': str(uuid4())}, configuration.json['csrf_token'])
    assert rejected.status_code == 400 and rejected.json['code'] == 'captcha_required'
    assert 'session' not in rejected.json
    assert counts(entry_app) == (0, 0, 0, 0)


def test_fast_entry_result_does_not_override_later_expiry_validation(entry_app):
    client = entry_app.test_client()
    proof = csrf(client, entry=True).json['csrf_token']
    device = str(uuid4())
    linked = post(client, '/api/survey/links', {'deviceId': device}, proof)
    assert linked.json['session']['status'] == 'active'
    with entry_app.app_context():
        SurveyInvitation.query.one().expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
    rejected = post(client, '/api/survey/session', {'token': linked.json['token'], 'deviceId': device}, proof)
    assert rejected.status_code == 410 and rejected.json['code'] == 'link_expired'
