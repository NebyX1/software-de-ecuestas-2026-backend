import pytest
import fakeredis
from flask import Flask
from app import create_app
from app.config import build_config, validate_config


@pytest.fixture
def production_config(monkeypatch):
    monkeypatch.setattr('app.utils.connector_security.verify_native_connector', lambda: '3.4.9')
    app = Flask('deployment-config')
    app.config.update(build_config('production'))
    app.config.update(SECRET_KEY='s' * 48, IDENTITY_HMAC_KEY='h' * 48,
                      SQLALCHEMY_DATABASE_URI='mariadb+mariadbconnector://user:password@db/survey',
                      REDIS_URL='redis://redis:6379/0', FRONTEND_URL='https://survey.example.org',
                      CORS_ALLOWED_ORIGINS=['https://survey.example.org'],
                      TRUSTED_HOSTS=['survey.example.org', 'localhost', '127.0.0.1'],
                      MAIL_SERVER='smtp.example.org', MAIL_DEFAULT_SENDER='survey@example.org',
                      MAIL_USE_TLS=True, MAIL_USE_SSL=False, TURNSTILE_REQUIRED=False)
    return app


@pytest.mark.parametrize('origin', ['', 'http://survey.example.org', 'https://',
    'https://*.example.org', 'https://survey.example.org/', 'https://survey.example.org/api',
    'https://user:password@survey.example.org', 'https://survey.example.org?debug=1',
    'https://survey.example.org#fragment', 'https://survey.example.org:abc',
    'https://survey.example.org:0', 'https://survey.example.org:65536', 'https://survey. example.org'])
def test_production_rejects_invalid_cors_origin(production_config, origin):
    production_config.config['CORS_ALLOWED_ORIGINS'] = [origin]
    with pytest.raises(ValueError, match='CORS'):
        validate_config(production_config)


@pytest.mark.parametrize('changes,message', [
    ({'CORS_ALLOWED_ORIGINS': []}, 'CORS'),
    ({'CORS_ALLOWED_ORIGINS': ['https://another.example.org']}, 'CORS_ORIGINS'),
    ({'FRONTEND_URL': 'https://survey.example.org/participar'}, 'FRONTEND_URL'),
    ({'TRUSTED_HOSTS': ['localhost', '127.0.0.1']}, 'TRUSTED_HOSTS'),
    ({'MAIL_SERVER': ''}, 'SMTP'),
    ({'MAIL_DEFAULT_SENDER': ''}, 'SMTP'),
])
def test_incomplete_deployment_fails_before_startup(production_config, changes, message):
    production_config.config.update(changes)
    with pytest.raises(ValueError, match=message):
        validate_config(production_config)


def test_production_accepts_https_origin_with_explicit_port(production_config):
    production_config.config.update(FRONTEND_URL='https://survey.example.org:8443',
        CORS_ALLOWED_ORIGINS=['https://survey.example.org:8443'])
    validate_config(production_config)


def test_cors_preflight_allows_only_the_configured_origin():
    app = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(),
        'CORS_ALLOWED_ORIGINS': ['https://survey.example.org']})
    client = app.test_client()
    for origin, allowed in [('https://survey.example.org', True),
                            ('https://survey.example.org.evil.test', False),
                            ('https://other.example.org', False), ('http://survey.example.org', False)]:
        response = client.options('/api/survey/links', headers={'Origin': origin,
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,x-csrftoken'})
        assert response.status_code == 200
        assert response.headers.get('Access-Control-Allow-Origin') == (origin if allowed else None)
        assert response.headers.get('Access-Control-Allow-Credentials') == ('true' if allowed else None)
        if allowed:
            assert 'POST' in response.headers['Access-Control-Allow-Methods']
            assert 'x-csrftoken' in response.headers['Access-Control-Allow-Headers'].lower()


@pytest.fixture
def two_domain_app():
    return create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(),
        'FRONTEND_URL': 'https://uypolls.online',
        'CORS_ALLOWED_ORIGINS': ['https://uypolls.online'],
        'TRUSTED_HOSTS': ['uypolls.online', 'mapi.uypolls.online', 'localhost', '127.0.0.1'],
        'WTF_CSRF_ENABLED': True, 'SESSION_COOKIE_SECURE': True})


@pytest.mark.parametrize('host,other_host', [
    ('uypolls.online', 'mapi.uypolls.online'), ('mapi.uypolls.online', 'uypolls.online')])
def test_https_post_checks_the_referer_on_each_domain(two_domain_app, host, other_host):
    client = two_domain_app.test_client()
    origin = 'https://' + host
    csrf = client.get('/api/csrf', base_url=origin).get_json()['csrf_token']
    # The empty payload reaches schema validation only after SSL CSRF passes.
    valid = client.post('/api/survey/links', base_url=origin, json={},
        headers={'X-CSRFToken': csrf, 'Referer': origin + '/participar'})
    assert valid.status_code == 422
    assert valid.get_json()['code'] == 'validation_error'
    foreign = client.post('/api/survey/links', base_url=origin, json={},
        headers={'X-CSRFToken': csrf, 'Referer': 'https://' + other_host + '/participar'})
    assert foreign.status_code == 400
    assert foreign.get_json()['code'] == 'csrf_invalid'
    assert client.get('/admin/login', base_url=origin).status_code == 200


def test_two_domains_keep_independent_host_cookies_and_exact_cors(two_domain_app):
    client = two_domain_app.test_client()
    frontend = 'https://uypolls.online'
    backend = 'https://mapi.uypolls.online'
    for origin in (frontend, backend):
        response = client.get('/api/csrf', base_url=origin)
        cookie = response.headers['Set-Cookie']
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
        assert 'Domain=' not in cookie
    public_cookie = client.get_cookie('survey_session', domain='uypolls.online')
    admin_cookie = client.get_cookie('survey_session', domain='mapi.uypolls.online')
    assert public_cookie and admin_cookie and public_cookie.value != admin_cookie.value
    client.get('/api/csrf', base_url=frontend)
    assert client.get_cookie('survey_session', domain='uypolls.online').value == public_cookie.value
    for origin, allowed in [(frontend, True), (backend, False), ('https://uypolls.online.evil.test', False)]:
        response = client.options('/api/survey/links', base_url=backend, headers={
            'Origin': origin, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type,x-csrftoken'})
        assert response.status_code == 200
        assert response.headers.get('Access-Control-Allow-Origin') == (origin if allowed else None)
        assert response.headers.get('Access-Control-Allow-Credentials') == ('true' if allowed else None)
