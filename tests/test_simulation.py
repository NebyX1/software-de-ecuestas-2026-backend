"""Exercise the full simulation boundary without touching production records."""
import copy
import csv
import io
import re

import pytest
from sqlalchemy import event
from redis.exceptions import ConnectionError as RedisConnectionError

from app.extensions import db
from app.models.user import User
from app.models.survey import SurveyInvitation, SurveyResponse, ParticipantIdentity, ResponseValue
from app.services.analytics_service import csv_columns, dashboard_data, iter_csv
from app.services.simulation_service import enable_simulation
from test_platform import platform_app, authenticated  # noqa: F401
from test_survey import answers, begin, challenge  # noqa: F401
from test_conditional_flow import residence_paths, MUNICIPAL_BLOCK


def access(client, app):
    with app.app_context():
        enable_simulation()
    result = client.post('/api/simulation/login', json={'email': 'operator@example.org', 'password': 'correct-password-2026!'})
    assert result.status_code == 200, result.json
    return {'runId': result.json['runId']}


def verification(client, run):
    result = client.post('/api/simulation/challenge', json=run)
    assert result.status_code == 200, result.json
    return {'challengeId': result.json['challengeId'], 'challengeAnswer': str(sum(map(int, re.findall(r'\d+', result.json['question']))))}


def payload(client, run, answers):
    return {**run, **verification(client, run), 'phone': '099123456', 'answers': answers,
            'consent': True, 'consentVersion': '2026-02', 'clientMetadata': {'language': 'es-UY', 'timezone': 'America/Montevideo'}}


def survey_counts():
    return [model.query.count() for model in (SurveyInvitation, SurveyResponse, ParticipantIdentity, ResponseValue)]


def test_disabled_by_default_and_no_unprotected_access(platform_app, answers):
    client = platform_app.test_client()
    assert client.get('/api/simulation/session').json['status'] == 'disabled'
    assert client.post('/api/simulation/login', json={'email': 'operator@example.org', 'password': 'correct-password-2026!'}).status_code == 403
    assert client.post('/api/simulation/challenge', json={'runId': 'x' * 43}).status_code == 403
    assert client.post('/api/simulation/export.csv', json={}).status_code == 403
    assert client.get('/admin/simulation').status_code == 302
    for action in ('enable', 'disable', 'restart'):
        assert client.post('/admin/simulation/' + action).status_code == 302
    with platform_app.app_context():
        enable_simulation()
    assert client.get('/api/simulation/session').json['status'] == 'unauthenticated'
    assert client.post('/api/simulation/export.csv', json={}).status_code == 401


def test_credentials_are_scoped_and_cookie_is_private(platform_app):
    client = platform_app.test_client()
    access(client, platform_app)
    assert client.get('/api/simulation/session').json['status'] == 'active'
    # Simulation login must not bypass the normal admin password + mail 2FA.
    assert client.get('/admin/dashboard').status_code == 302
    for action in ('enable', 'disable', 'restart'):
        assert client.post('/admin/simulation/' + action).status_code == 302
    cookie = client.get_cookie('survey_simulation', path='/api/simulation')
    assert cookie.http_only and cookie.same_site == 'Strict'
    stranger = platform_app.test_client()
    assert stranger.get('/api/simulation/session').json['status'] == 'unauthenticated'
    assert stranger.post('/api/simulation/challenge', json={'runId': 'x' * 43}).status_code == 401


@pytest.mark.parametrize('email,password', [('missing@example.org', 'invalid'), ('operator@example.org', 'invalid')])
def test_invalid_credentials(platform_app, email, password):
    client = platform_app.test_client()
    with platform_app.app_context():
        enable_simulation()
    assert client.post('/api/simulation/login', json={'email': email, 'password': password}).status_code == 401
    assert client.get('/api/simulation/session').json['status'] == 'unauthenticated'


def test_export_and_controls_perform_no_sql_writes(platform_app, answers):
    admin, tester = platform_app.test_client(), platform_app.test_client()
    authenticated(admin, platform_app, 'operator')
    statements = []

    def no_writes(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert not statement.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'REPLACE '))

    with platform_app.app_context():
        before = survey_counts()
        csv_before = ''.join(iter_csv({}))
        analytics_before = dashboard_data({})
        engine = db.engine
    event.listen(engine, 'before_cursor_execute', no_writes)
    try:
        assert admin.post('/admin/simulation/enable').status_code == 302
        assert 'Simular' in admin.get('/admin/simulation').text
        run = access(tester, platform_app)
        exported = tester.post('/api/simulation/export.csv', json=payload(tester, run, answers))
        assert exported.status_code == 200, exported.text
        assert exported.headers['Content-Type'] == 'text/csv; charset=utf-8'
        assert 'simulacion_' in exported.headers['Content-Disposition']
        assert exported.data.startswith(b'\xef\xbb\xbf')
        assert 'no-store' in exported.headers['Cache-Control']
        rows = list(csv.reader(io.StringIO(exported.data.decode('utf-8-sig'), newline='')))
        assert rows[0] == csv_columns()
        assert len(rows) == 2 and len(rows[0]) == len(rows[1])
        record = dict(zip(rows[0], rows[1]))
        assert record['id'].startswith('SIMULACION-')
        assert record['openComment'] == answers['openComment']
        assert record['technical_language'] == 'es-UY'
        assert '099123456' not in exported.text and '+59899123456' not in exported.text
        assert admin.post('/admin/simulation/restart').status_code == 302
        assert tester.get('/api/simulation/session').json['status'] == 'unauthenticated'
        assert admin.post('/admin/simulation/disable').status_code == 302
        assert tester.get('/api/simulation/session').json['status'] == 'disabled'
        with platform_app.app_context():
            assert survey_counts() == before
            assert ''.join(iter_csv({})) == csv_before
            assert dashboard_data({}) == analytics_before
            redis_values = [platform_app.extensions['redis'].get(key) for key in platform_app.extensions['redis'].scan_iter('simulation:*')]
            assert all(answers['openComment'].encode() not in value for value in redis_values if value)
    finally:
        event.remove(engine, 'before_cursor_execute', no_writes)
    assert statements


def test_restart_disable_reenable_and_expiry_revoke_old_sessions(platform_app, answers):
    admin, tester = platform_app.test_client(), platform_app.test_client()
    authenticated(admin, platform_app)
    run = access(tester, platform_app)
    pending = payload(tester, run, answers)
    assert admin.post('/admin/simulation/enable').status_code == 302  # Repeated enable preserves the current run.
    assert tester.get('/api/simulation/session').json['runId'] == run['runId']
    assert admin.post('/admin/simulation/restart').status_code == 302
    assert tester.post('/api/simulation/export.csv', json=pending).status_code == 401
    new_run = access(tester, platform_app)
    assert new_run != run
    # An old page cannot submit its old draft using a newly logged-in cookie.
    assert tester.post('/api/simulation/export.csv', json=pending).status_code == 401
    pending = payload(tester, new_run, answers)
    assert admin.post('/admin/simulation/disable').status_code == 302
    assert tester.post('/api/simulation/export.csv', json=pending).status_code == 403
    assert admin.post('/admin/simulation/enable').status_code == 302
    assert tester.post('/api/simulation/export.csv', json=pending).status_code == 401
    access(tester, platform_app)
    with platform_app.app_context():
        redis = platform_app.extensions['redis']
        for key in list(redis.scan_iter('simulation:session:*')):
            redis.delete(key)
    assert tester.get('/api/simulation/session').json['status'] == 'unauthenticated'


def test_account_revocation_and_logout(platform_app):
    client = platform_app.test_client()
    run = access(client, platform_app)
    with platform_app.app_context():
        user = User.query.filter_by(username='operator').one()
        user.auth_version += 1
        db.session.commit()
    assert client.post('/api/simulation/challenge', json=run).status_code == 401
    access(client, platform_app)
    assert client.post('/api/simulation/logout', json={}).status_code == 200
    assert client.get('/api/simulation/session').json['status'] == 'unauthenticated'
    assert client.get_cookie('survey_simulation', path='/api/simulation') is None
    with platform_app.app_context():
        user = User.query.filter_by(username='operator').one()
        user.is_active = False
        db.session.commit()
    assert client.post('/api/simulation/login', json={'email': 'operator@example.org', 'password': 'correct-password-2026!'}).status_code == 401


@pytest.mark.parametrize('locality,membership,expected', list(residence_paths()))
def test_same_municipality_validation_as_real_form(platform_app, answers, locality, membership, expected):
    client = platform_app.test_client()
    run = access(client, platform_app)
    opinions = {**answers, 'locality': locality}
    if membership is not None:
        opinions['municipality'] = membership
    if expected:
        opinions.update(MUNICIPAL_BLOCK)
    data = payload(client, run, opinions)
    bad = copy.deepcopy(opinions)
    if expected:
        del bad['municipalityEvaluation']
    else:
        bad.update(MUNICIPAL_BLOCK)
    assert client.post('/api/simulation/export.csv', json={**data, 'answers': bad}).status_code == 422
    result = client.post('/api/simulation/export.csv', json=data)
    assert result.status_code == 200
    row = list(csv.DictReader(io.StringIO(result.data.decode('utf-8-sig'))))[0]
    assert row['municipality'] == (expected or membership or '')
    assert row['municipalityEvaluation'] == ('buena' if expected else '')


def test_csv_quotes_unicode_formulas_and_repeated_phones(platform_app, answers):
    client = platform_app.test_client()
    run = access(client, platform_app)
    for comment in ['Opinión, "con comillas"\ny salto de línea: ñ.', '=HYPERLINK("https://example.org")']:
        result = client.post('/api/simulation/export.csv', json=payload(client, run, {**answers, 'openComment': comment}))
        assert result.status_code == 200
        row = list(csv.DictReader(io.StringIO(result.data.decode('utf-8-sig'), newline='')))[0]
        assert row['openComment'] == ("'" + comment if comment.startswith('=') else comment)
    with platform_app.app_context():
        assert survey_counts() == [0, 0, 0, 0]


def test_real_and_simulated_challenges_and_device_claims_are_separate(platform_app, answers):
    client = platform_app.test_client()
    invitation = begin(client)
    real_challenge = challenge(client, invitation)
    run = access(client, platform_app)
    data = payload(client, run, answers)
    assert client.post('/api/simulation/export.csv', json={**data, **real_challenge}).status_code == 400
    assert client.post('/api/simulation/export.csv', json=data).status_code == 200
    # Finishing a simulation must not consume a real link or claim a phone/device.
    real = client.post('/api/survey/responses', json={**invitation, **real_challenge, 'answers': answers,
                       'phone': '099123456', 'consent': True, 'consentVersion': '2026-02'})
    assert real.status_code == 201, real.json
    # A real device already marked as completed can continue testing.
    assert client.post('/api/simulation/export.csv', json=payload(client, run, answers)).status_code == 200
    with platform_app.app_context():
        assert SurveyResponse.query.count() == 1


def test_security_controls_cannot_be_bypassed(platform_app, answers):
    client = platform_app.test_client()
    run = access(client, platform_app)
    data = payload(client, run, answers)
    for patch in [{'phone': '123'}, {'consent': False}, {'consent': 'true'}, {'answers': {**answers, 'party2025': 'pnr'}}, {'deviceId': '0' * 36}, {'token': 'x' * 43}]:
        assert client.post('/api/simulation/export.csv', json={**data, **patch}).status_code == 422
    assert client.post('/api/simulation/export.csv', json={**data, 'website': 'spam'}).status_code == 400
    assert client.post('/api/simulation/export.csv', json={**data, 'challengeAnswer': '9999'}).status_code == 400
    assert client.post('/api/simulation/export.csv', json=data).status_code == 200
    assert client.post('/api/simulation/export.csv', json=data).status_code == 409
    with platform_app.app_context():
        assert survey_counts() == [0, 0, 0, 0]


def test_csrf_is_required_for_control_login_and_export(platform_app, answers):
    admin, tester = platform_app.test_client(), platform_app.test_client()
    authenticated(admin, platform_app)
    run = access(tester, platform_app)
    data = payload(tester, run, answers)
    platform_app.config['WTF_CSRF_ENABLED'] = True
    assert admin.post('/admin/simulation/disable').status_code == 400
    assert tester.post('/api/simulation/login', json={'email': 'operator@example.org', 'password': 'correct-password-2026!'}).status_code == 400
    assert tester.post('/api/simulation/export.csv', json=data).status_code == 400
    token = tester.get('/api/csrf').json['csrf_token']
    assert tester.post('/api/simulation/export.csv', json=data, headers={'X-CSRFToken': token}).status_code == 200


def test_redis_outage_denies_access_and_export(platform_app, answers, monkeypatch):
    client = platform_app.test_client()
    run = access(client, platform_app)
    data = payload(client, run, answers)

    def unavailable(*args, **kwargs):
        raise RedisConnectionError('unavailable')

    monkeypatch.setattr(platform_app.extensions['redis'], 'get', unavailable)
    assert client.get('/api/simulation/session').status_code == 503
    result = client.post('/api/simulation/export.csv', json=data)
    assert result.status_code == 503 and result.json['code'] == 'service_unavailable'
    with platform_app.app_context():
        assert survey_counts() == [0, 0, 0, 0]


def test_https_cookie_security(platform_app):
    platform_app.config['SESSION_COOKIE_SECURE'] = True
    client = platform_app.test_client()
    with platform_app.app_context():
        enable_simulation()
    result = client.post('/api/simulation/login', base_url='https://uypolls.online', json={
        'email': 'operator@example.org', 'password': 'correct-password-2026!',
    })
    cookie = result.headers.getlist('Set-Cookie')[0]
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
    assert 'Path=/api/simulation' in cookie


def test_account_rate_limit_survives_ip_rotation():
    import fakeredis
    from uuid import uuid4
    from app import create_app

    app = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(), 'RATELIMIT_ENABLED': True,
                                 'RATELIMIT_KEY_PREFIX': 'simulation-test-' + str(uuid4())})
    with app.app_context():
        db.create_all()
        enable_simulation()
    try:
        client = app.test_client()
        for index in range(10):
            result = client.post('/api/simulation/login', json={'email': 'missing@example.org', 'password': 'incorrect'},
                                 environ_overrides={'REMOTE_ADDR': f'203.0.113.{index + 1}'})
            assert result.status_code == 401
        blocked = client.post('/api/simulation/login', json={'email': 'missing@example.org', 'password': 'incorrect'},
                              environ_overrides={'REMOTE_ADDR': '203.0.113.100'})
        assert blocked.status_code == 429
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
