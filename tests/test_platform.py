from datetime import datetime, timedelta
import re
from pathlib import Path
import fakeredis
import pytest
from app import create_app
from app.extensions import db, mail
from app.models.user import User, TwoFactorCode
from app.models.audit import ActivityLog


@pytest.fixture
def platform_app(tmp_path):
    app = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(), 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{(tmp_path / "test.sqlite").as_posix()}', 'MAIL_DEFAULT_SENDER': 'test@example.org'})
    with app.app_context():
        db.create_all()
        for name, is_super in [('superadmin', True), ('operator', False)]:
            user = User(username=name, email=f'{name}@example.org', is_active=True, is_superuser=is_super)
            user.set_password('correct-password-2026!')
            db.session.add(user)
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def begin_login(client, app, name='superadmin'):
    page = client.get('/admin/login')
    assert page.status_code == 200
    with client.session_transaction() as session:
        verifier = session['captcha_result']
    with app.app_context(), mail.record_messages() as messages:
        response = client.post('/admin/login', data={'email': f'{name}@example.org', 'password': 'correct-password-2026!', 'captcha': str(verifier)})
        assert response.status_code == 302
        assert response.location.endswith('/admin/2fa')
        assert len(messages) == 1
        code = re.search(r'\b\d{6}\b', messages[0].body).group()
    return code


def authenticated(client, app, name='superadmin'):
    code = begin_login(client, app, name)
    result = client.post('/admin/2fa', data={'code': code})
    assert result.status_code == 302
    assert result.location.endswith('/admin/dashboard')


def test_password_alone_does_not_authenticate(platform_app):
    client = platform_app.test_client()
    begin_login(client, platform_app)
    assert client.get('/admin/dashboard').status_code == 302
    with client.session_transaction() as session:
        assert '_user_id' not in session


def test_verifier_is_single_use(platform_app):
    client = platform_app.test_client()
    client.get('/admin/login')
    with client.session_transaction() as session:
        answer = session['captcha_result']
    assert client.post('/admin/login', data={'email': 'superadmin@example.org', 'password': 'incorrect', 'captcha': answer}).status_code == 400
    # A form created before a fresh verifier cannot replay the old value.
    with client.session_transaction() as session:
        session.pop('captcha_result', None)
    assert client.post('/admin/login', data={'email': 'superadmin@example.org', 'password': 'correct-password-2026!', 'captcha': answer}).status_code == 400


def test_otp_consumed_and_not_logged(platform_app, caplog):
    client = platform_app.test_client()
    code = begin_login(client, platform_app)
    with client.session_transaction() as session:
        old_challenge = session['2fa_challenge']
        old_user = session['2fa_user_id']
    assert client.post('/admin/2fa', data={'code': code}).status_code == 302
    assert client.get('/admin/dashboard').status_code == 200
    with platform_app.app_context():
        assert TwoFactorCode.query.one().consumed_at is not None
        assert ActivityLog.query.filter_by(action='LOGIN').count() == 1
    other = platform_app.test_client()
    with other.session_transaction() as session:
        session['2fa_challenge'] = old_challenge
        session['2fa_user_id'] = old_user
    assert other.post('/admin/2fa', data={'code': code}).status_code == 302
    assert other.get('/admin/dashboard').status_code == 302
    assert code not in caplog.text


def test_otp_attempt_limit(platform_app):
    client = platform_app.test_client()
    code = begin_login(client, platform_app)
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(5):
        assert client.post('/admin/2fa', data={'code': wrong}).status_code == 400
    assert client.post('/admin/2fa', data={'code': code}).status_code == 302
    assert client.get('/admin/dashboard').status_code == 302
    with platform_app.app_context():
        challenge = TwoFactorCode.query.one()
        assert challenge.attempts == 5 and challenge.consumed_at is not None


def test_expired_otp_does_not_authenticate(platform_app):
    client = platform_app.test_client()
    code = begin_login(client, platform_app)
    with platform_app.app_context():
        TwoFactorCode.query.one().expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
    client.post('/admin/2fa', data={'code': code})
    assert client.get('/admin/dashboard').status_code == 302


def test_new_login_invalidates_previous_otp(platform_app):
    first, second = platform_app.test_client(), platform_app.test_client()
    old_code = begin_login(first, platform_app)
    new_code = begin_login(second, platform_app)
    first.post('/admin/2fa', data={'code': old_code})
    assert first.get('/admin/dashboard').status_code == 302
    second.post('/admin/2fa', data={'code': new_code})
    assert second.get('/admin/dashboard').status_code == 200


def test_disabled_account_invalidates_pending_challenge(platform_app):
    client = platform_app.test_client()
    code = begin_login(client, platform_app, 'operator')
    with platform_app.app_context():
        User.query.filter_by(username='operator').one().is_active = False
        db.session.commit()
    client.post('/admin/2fa', data={'code': code})
    assert client.get('/admin/dashboard').status_code == 302


def test_smtp_failure_fails_closed(platform_app, monkeypatch):
    client = platform_app.test_client()
    client.get('/admin/login')
    with client.session_transaction() as session:
        verifier = session['captcha_result']
    def fail_send(_):
        raise OSError('SMTP unavailable')
    monkeypatch.setattr(mail, 'send', fail_send)
    response = client.post('/admin/login', data={'email': 'superadmin@example.org', 'password': 'correct-password-2026!', 'captcha': verifier})
    assert response.status_code == 503
    with client.session_transaction() as session:
        assert '2fa_challenge' not in session
    with platform_app.app_context():
        assert TwoFactorCode.query.one().consumed_at is not None


def test_admin_rbac_and_export_are_protected(platform_app):
    client = platform_app.test_client()
    assert client.get('/admin/responses/export.csv').status_code == 302
    authenticated(client, platform_app, 'operator')
    for path in ('/admin/users', '/admin/logs', '/admin/logs/export'):
        assert client.get(path).status_code == 403
    for path in ('/admin/dashboard', '/admin/responses', '/admin/responses/export.csv'):
        assert client.get(path).status_code == 200


def test_auth_version_revokes_session(platform_app):
    client = platform_app.test_client()
    authenticated(client, platform_app, 'operator')
    with platform_app.app_context():
        user = User.query.filter_by(username='operator').one()
        user.auth_version += 1
        db.session.commit()
    assert client.get('/admin/dashboard').status_code == 302


def test_logout_invalidates_replay_of_previous_cookie(platform_app):
    client = platform_app.test_client()
    authenticated(client, platform_app, 'operator')
    old_cookie = client.get_cookie(platform_app.config['SESSION_COOKIE_NAME']).value
    clone = platform_app.test_client()
    clone.set_cookie(platform_app.config['SESSION_COOKIE_NAME'], old_cookie)
    assert clone.get('/admin/dashboard').status_code == 200
    client.post('/admin/logout')
    assert clone.get('/admin/dashboard').status_code == 302


def test_lost_redis_session_fails_closed(platform_app):
    client = platform_app.test_client()
    authenticated(client, platform_app, 'operator')
    platform_app.extensions['redis'].flushdb()
    assert client.get('/admin/dashboard').status_code == 302


def test_last_superadmin_cannot_be_demoted_or_disabled(platform_app):
    client = platform_app.test_client()
    authenticated(client, platform_app)
    with platform_app.app_context():
        user_id = User.query.filter_by(username='superadmin').one().id
    response = client.post(f'/admin/users/{user_id}/edit', data={'username': 'superadmin', 'email': 'superadmin@example.org', 'is_active': 'y'})
    assert response.status_code == 400
    client.post(f'/admin/users/{user_id}/delete')
    with platform_app.app_context():
        user = db.session.get(User, user_id)
        assert user.is_active and user.is_superuser


def test_admin_update_revokes_other_user_session(platform_app):
    super_client, operator = platform_app.test_client(), platform_app.test_client()
    authenticated(super_client, platform_app)
    authenticated(operator, platform_app, 'operator')
    with platform_app.app_context():
        user_id = User.query.filter_by(username='operator').one().id
    assert super_client.post(f'/admin/users/{user_id}/edit', data={'username': 'operator', 'email': 'operator@example.org', 'is_active': 'y'}).status_code == 302
    assert operator.get('/admin/dashboard').status_code == 302


def test_admin_password_change_requires_confirmation(platform_app):
    client = platform_app.test_client()
    authenticated(client, platform_app)
    with platform_app.app_context():
        user_id = User.query.filter_by(username='operator').one().id
    response = client.post(f'/admin/users/{user_id}/edit', data={'username': 'operator', 'email': 'operator@example.org', 'is_active': 'y', 'password': 'a-new-password-2026', 'confirm_password': ''})
    assert response.status_code == 400
    with platform_app.app_context():
        assert db.session.get(User, user_id).check_password('correct-password-2026!')


def test_logout_requires_post_and_csrf(platform_app):
    client = platform_app.test_client()
    authenticated(client, platform_app)
    assert client.get('/admin/logout').status_code == 405
    platform_app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/admin/logout').status_code == 400
    csrf = client.get('/api/csrf').get_json()['csrf_token']
    assert client.post('/admin/logout', data={'csrf_token': csrf}).status_code == 302
    assert client.get('/admin/dashboard').status_code == 302


def test_public_api_csrf_is_required(platform_app):
    platform_app.config['WTF_CSRF_ENABLED'] = True
    response = platform_app.test_client().post('/api/survey/links', json={'deviceId': '431d4207-312f-4376-aeda-76d2b655b7bc'})
    assert response.status_code == 400
    assert response.get_json()['code'] == 'csrf_invalid'


def test_headers_do_not_cache_sensitive_pages(platform_app):
    client = platform_app.test_client()
    authenticated(client, platform_app)
    response = client.get('/admin/dashboard')
    assert response.headers['Cache-Control'] == 'no-store, private'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert 'unsafe-inline' not in response.headers['Content-Security-Policy']


def test_populated_dashboard_list_detail_and_csv(platform_app):
    from app.models.survey import SurveyResponse
    from app.repositories.survey import add_values
    with platform_app.app_context():
        row = SurveyResponse(survey_id=platform_app.config['SURVEY_ID'], consent_version='2026-01', answers={'locality': 'minas', 'gender': 'femenino', 'generalEvaluation': 'buena', 'openComment': '<script>alert(1)</script>'})
        db.session.add(row)
        db.session.flush()
        add_values(row)
        db.session.commit()
        row_id = row.id
    client = platform_app.test_client()
    authenticated(client, platform_app)
    dashboard = client.get('/admin/dashboard?locality=minas')
    assert dashboard.status_code == 200
    assert b'bar-svg' in dashboard.data
    assert client.get('/admin/responses?locality=minas').status_code == 200
    detail = client.get(f'/admin/responses/{row_id}')
    assert detail.status_code == 200
    assert b'&lt;script&gt;' in detail.data and b'<script>alert(1)</script>' not in detail.data
    export = client.get('/admin/responses/export.csv?locality=minas')
    assert export.status_code == 200 and row_id.encode() in export.data
    assert client.get('/admin/dashboard?gender=unsupported').status_code == 422
    assert client.get('/admin/responses/export.csv?date_from=invalid').status_code == 422


def test_trusted_proxy_normalization_and_hosts():
    from flask import request, jsonify
    app = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(), 'TRUSTED_PROXY_COUNT': 1, 'TRUSTED_HOSTS': ['survey.example.org']})
    @app.get('/api/test-network-context')
    def network_context():
        return jsonify(ip=request.remote_addr, secure=request.is_secure)
    client = app.test_client()
    result = client.get('/api/test-network-context', base_url='http://survey.example.org', headers={'X-Forwarded-For': '192.0.2.123, 203.0.113.4', 'X-Forwarded-Proto': 'https'})
    assert result.get_json() == {'ip': '203.0.113.4', 'secure': True}
    assert client.get('/api/test-network-context', base_url='http://evil.example.org').status_code == 400


def test_smtp_uses_verified_tls_timeout_and_no_debug(platform_app, monkeypatch):
    import ssl
    from app.services.mail_service import BoundedConnection
    captured = {}
    class FakeSMTP:
        def set_debuglevel(self, level):
            captured['debug'] = level
        def starttls(self, context):
            captured['context'] = context
        def login(self, username, password):
            captured['auth'] = (username, password)
    def fake_smtp(server, port, **kwargs):
        captured.update(kwargs)
        return FakeSMTP()
    monkeypatch.setattr('app.services.mail_service.smtplib.SMTP', fake_smtp)
    with platform_app.app_context():
        BoundedConnection(platform_app.extensions['mail']).configure_host()
    assert captured['timeout'] == 10
    assert captured['debug'] == 0
    assert captured['context'].verify_mode == ssl.CERT_REQUIRED
    assert captured['context'].check_hostname


def test_create_admin_cli_and_duplicate_error(platform_app):
    runner = platform_app.test_cli_runner()
    args = ['create-admin', 'newadmin', 'new@example.org', 'a-strong-password-2026', 'true']
    assert runner.invoke(args=args).exit_code == 0
    assert runner.invoke(args=args).exit_code != 0
    assert runner.invoke(args=['create-admin', 'otheradmin', 'other@example.org', 'weak', 'false']).exit_code != 0
    assert runner.invoke(args=['create-admin', 'thirdadmin', 'third@example.org', 'a-strong-password-2026', 'maybe']).exit_code != 0


def test_readiness_fails_when_redis_unavailable(platform_app, monkeypatch):
    monkeypatch.setattr(platform_app.extensions['redis'], 'ping', lambda: (_ for _ in ()).throw(OSError('unavailable')))
    assert platform_app.test_client().get('/health/ready').status_code == 503
    assert platform_app.test_client().get('/health/live').status_code == 200


def production_settings():
    from flask import Flask
    from app.config import build_config
    app = Flask('production-config-test')
    app.config.update(build_config('production'))
    app.config.update(SECRET_KEY='s' * 48, IDENTITY_HMAC_KEY='h' * 48, SQLALCHEMY_DATABASE_URI='mariadb+mariadbconnector://user:password@database/app', REDIS_URL='redis://localhost:6379/0', FRONTEND_URL='https://survey.example.org', CORS_ALLOWED_ORIGINS=['https://survey.example.org'], TRUSTED_HOSTS=['survey.example.org'], MAIL_SERVER='smtp.example.org', MAIL_DEFAULT_SENDER='app@example.org', MAIL_USE_TLS=True, MAIL_USE_SSL=False, TURNSTILE_REQUIRED=False)
    return app


def test_production_builtin_antibot_needs_no_sms_provider(monkeypatch):
    from app.config import validate_config
    monkeypatch.setattr('app.utils.connector_security.verify_native_connector', lambda: '3.4.9')
    app = production_settings()
    validate_config(app)
    assert app.config['SURVEY_MIN_FILL_SECONDS'] == 15
    assert app.config['SURVEY_CHALLENGE_TTL_SECONDS'] == 300
    assert app.config['SURVEY_CHALLENGE_MAX_ATTEMPTS'] == 5
    assert not any(key.startswith('TWILIO_') for key in app.config)
    assert 'PHONE_VERIFICATION_REQUIRED' not in app.config


def test_optional_turnstile_requires_credentials_if_enabled():
    from app.config import validate_config
    app = production_settings()
    app.config.update(TURNSTILE_REQUIRED=True, TURNSTILE_SECRET_KEY='', TURNSTILE_HOSTNAME='')
    with pytest.raises(ValueError, match='TURNSTILE_SECRET_KEY'):
        validate_config(app)


def test_builtin_antibot_still_requires_production_redis():
    from app.config import validate_config
    app = production_settings()
    app.config['REDIS_URL'] = 'memory://'
    with pytest.raises(ValueError, match='REDIS_URL'):
        validate_config(app)


def test_initial_migration_roundtrip(tmp_path):
    app = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(), 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{(tmp_path / "migration.sqlite").as_posix()}'})
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', '-d', migrations])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert set(db.inspect(db.engine).get_table_names()) >= {'users', 'two_factor_codes', 'activity_logs', 'survey_responses', 'survey_invitations', 'response_values', 'participant_identities'}
    result = runner.invoke(args=['db', 'downgrade', '-d', migrations, 'base'])
    assert result.exit_code == 0, result.output
    result = runner.invoke(args=['db', 'upgrade', '-d', migrations])
    assert result.exit_code == 0, result.output


def test_sms_removal_migration_preserves_opinions_and_duplicate_claims(tmp_path):
    from app.models.survey import SurveyResponse, ParticipantIdentity
    from sqlalchemy import text
    from uuid import uuid4
    app = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(), 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{(tmp_path / "remove-sms.sqlite").as_posix()}'})
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', '-d', migrations, '022a20c61d0e'])
    assert result.exit_code == 0, result.output
    invitation_id = str(uuid4())
    with app.app_context():
        # Insert against the historical schema, independent of newer ORM columns.
        opinion_id = str(uuid4())
        db.session.execute(text("INSERT INTO survey_responses (id,survey_id,answers,consent_version,consented_at,created_at) VALUES (:id,'preserve-study',:answers,'2026-01',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {'id': opinion_id, 'answers': '{"openComment":"Conservar esta opinión."}'})
        db.session.add(ParticipantIdentity(survey_id='preserve-study', kind='phone', digest='f' * 64))
        db.session.execute(text("INSERT INTO survey_invitations (id,survey_id,token_hash,device_hash,browser_hash,ip_hash,created_at,expires_at,phone_attempts,phone_send_count,attribution) VALUES (:id,'preserve-study',:token,:device,:browser,:ip,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,2,1,'{}')"), {'id': invitation_id, 'token': 'a' * 64, 'device': 'b' * 64, 'browser': 'c' * 64, 'ip': 'd' * 64})
        db.session.commit()
    result = runner.invoke(args=['db', 'upgrade', '-d', migrations])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert db.session.get(SurveyResponse, opinion_id).answers['openComment'] == 'Conservar esta opinión.'
        assert ParticipantIdentity.query.filter_by(survey_id='preserve-study', kind='phone').count() == 1
        assert db.session.execute(text('SELECT id FROM survey_invitations WHERE id = :id'), {'id': invitation_id}).scalar_one() == invitation_id
        columns = {column['name'] for column in db.inspect(db.engine).get_columns('survey_invitations')}
        assert not columns.intersection({'phone_hash', 'phone_verification_sid', 'phone_started_at', 'phone_verified_at', 'phone_attempts', 'phone_send_count'})
