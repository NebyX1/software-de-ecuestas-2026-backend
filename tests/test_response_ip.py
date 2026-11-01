"""Response IPs are server-observed, canonical and immutable after first commit."""
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import fakeredis
import pytest
from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db
from app.models.survey import SurveyInvitation, SurveyResponse
from app.services.survey_service import consume_challenge
from test_survey import answers, begin, challenge  # noqa: F401


@pytest.fixture
def make_ip_app():
    instances = []

    def make(**overrides):
        app = create_app('testing', {
            'REDIS_CLIENT': fakeredis.FakeRedis(),
            'SURVEY_ENFORCE_IP_UNIQUENESS': False,
            **overrides,
        })
        with app.app_context():
            db.create_all()
        instances.append(app)
        return app

    yield make
    for app in instances:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def prepared_payload(client, answers, phone='099123456', link_ip='192.0.2.10'):
    invitation = begin(client, ip=link_ip)
    proof = challenge(client, invitation, ip=link_ip)
    return {**invitation, **proof, 'phone': phone, 'answers': answers,
            'consent': True, 'consentVersion': '2026-02'}


@pytest.mark.parametrize('version', ['2026-01', '2026-02', '2026-03'])
def test_accepts_current_and_previous_notice_versions(make_ip_app, answers, version):
    app = make_ip_app()
    client = app.test_client()
    data = {**prepared_payload(client, answers), 'consentVersion': version}
    result = client.post('/api/survey/responses', json=data,
                         environ_overrides={'REMOTE_ADDR': '198.51.100.40'})
    assert result.status_code == 201, result.json
    with app.app_context():
        saved = SurveyResponse.query.one()
        assert saved.ip_address == '198.51.100.40'
        assert saved.consent_version == version


@pytest.mark.parametrize(('address', 'expected'), [
    ('198.51.100.27', '198.51.100.27'),
    ('2001:0DB8:0001:0002:0000:0000:ABCD:0042', '2001:db8:1:2::abcd:42'),
    ('::ffff:198.51.100.27', '198.51.100.27'),
])
def test_records_full_canonical_ip_at_submission_not_at_link_creation(make_ip_app, answers, address, expected):
    app = make_ip_app()
    client = app.test_client()
    data = prepared_payload(client, answers)
    response = client.post('/api/survey/responses', json=data, environ_overrides={'REMOTE_ADDR': address})
    assert response.status_code == 201, response.json
    with app.app_context():
        saved = SurveyResponse.query.one()
        assert saved.ip_address == expected
        assert 'ip_address' not in saved.answers
        assert expected not in response.get_data(as_text=True)


@pytest.mark.parametrize(('hops', 'expected'), [(0, '10.20.30.40'), (1, '203.0.113.77')])
def test_uses_only_configured_proxy_hop_and_ignores_spoofed_prefix(make_ip_app, answers, hops, expected):
    app = make_ip_app(TRUSTED_PROXY_COUNT=hops)
    client = app.test_client()
    data = prepared_payload(client, answers)
    result = client.post('/api/survey/responses', json=data,
        environ_overrides={'REMOTE_ADDR': '10.20.30.40'}, headers={
            'X-Forwarded-For': '198.51.100.99, 203.0.113.77',
            'X-Real-IP': '198.51.100.88', 'CF-Connecting-IP': '198.51.100.66'})
    assert result.status_code == 201, result.json
    with app.app_context():
        assert SurveyResponse.query.one().ip_address == expected


def test_idempotent_retry_from_another_ip_preserves_the_original_address(make_ip_app, answers):
    app = make_ip_app()
    client = app.test_client()
    data = prepared_payload(client, answers)
    first = client.post('/api/survey/responses', json=data, environ_overrides={'REMOTE_ADDR': '198.51.100.20'})
    assert first.status_code == 201
    repeated = client.post('/api/survey/responses', json=data, environ_overrides={'REMOTE_ADDR': '2001:db8::20'})
    assert repeated.status_code == 200 and repeated.json == first.json
    with app.app_context():
        assert SurveyResponse.query.count() == 1
        assert SurveyResponse.query.one().ip_address == '198.51.100.20'


@pytest.mark.parametrize('address', [None, '', 'not-an-ip', '198.51.100.27:443', 'fe80::1%eth0'])
def test_invalid_submission_ip_is_rejected_before_consuming_challenge(make_ip_app, answers, monkeypatch, address):
    app = make_ip_app()
    client = app.test_client()
    data = prepared_payload(client, answers)
    consume = Mock(wraps=consume_challenge)
    monkeypatch.setattr('app.services.survey_service.consume_challenge', consume)
    result = client.post('/api/survey/responses', json=data, environ_overrides={'REMOTE_ADDR': address})
    assert result.status_code == 503 and result.json['code'] == 'service_unavailable'
    consume.assert_not_called()
    with app.app_context():
        assert SurveyResponse.query.count() == 0
        assert SurveyInvitation.query.one().consumed_at is None
    retried = client.post('/api/survey/responses', json=data, environ_overrides={'REMOTE_ADDR': '203.0.113.3'})
    assert retried.status_code == 201
    assert consume.call_count == 1


def test_ip_cannot_be_supplied_as_a_response_json_field(make_ip_app, answers):
    app = make_ip_app()
    client = app.test_client()
    data = prepared_payload(client, answers)
    result = client.post('/api/survey/responses', json={**data, 'ip_address': '198.51.100.99'})
    assert result.status_code == 422
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_shared_network_can_record_distinct_participants(make_ip_app, answers):
    app = make_ip_app()
    for phone in ('099123456', '098123456'):
        client = app.test_client()
        data = prepared_payload(client, answers, phone=phone)
        result = client.post('/api/survey/responses', json=data, environ_overrides={'REMOTE_ADDR': '203.0.113.4'})
        assert result.status_code == 201
    with app.app_context():
        assert [row.ip_address for row in SurveyResponse.query.all()] == ['203.0.113.4', '203.0.113.4']


def test_ipv6_duplicate_signal_still_uses_the_same_64_prefix(make_ip_app, answers):
    app = make_ip_app(SURVEY_ENFORCE_IP_UNIQUENESS=True)
    client = app.test_client()
    data = prepared_payload(client, answers, link_ip='2001:db8:7:8::1')
    result = client.post('/api/survey/responses', json=data, environ_overrides={'REMOTE_ADDR': '2001:db8:7:8::abc'})
    assert result.status_code == 201
    with app.app_context():
        assert SurveyResponse.query.one().ip_address == '2001:db8:7:8::abc'
    duplicate = app.test_client().post('/api/survey/links', json={'deviceId': str(uuid4())},
        environ_overrides={'REMOTE_ADDR': '2001:db8:7:8::1234'})
    assert duplicate.status_code == 409 and duplicate.json['code'] == 'duplicate_response'


def test_ip_migration_preserves_old_opinions_without_inventing_addresses(tmp_path):
    app = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(),
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{(tmp_path / "response-ip.sqlite").as_posix()}'})
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', '-d', migrations, '9a7e3c2d1f60'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        db.session.execute(text("INSERT INTO survey_responses (id,survey_id,answers,consent_version,consented_at,created_at) VALUES ('historical','test','{\"adult\":\"si\"}','2026-01',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.session.commit()
    for operation, target in [('upgrade', 'head'), ('downgrade', '9a7e3c2d1f60'), ('upgrade', 'head')]:
        result = runner.invoke(args=['db', operation, '-d', migrations, target])
        assert result.exit_code == 0, result.output
        with app.app_context():
            row = db.session.execute(text('SELECT id, answers FROM survey_responses')).one()
            assert row.id == 'historical' and 'adult' in row.answers
            if operation == 'upgrade':
                column = next(c for c in inspect(db.engine).get_columns('survey_responses') if c['name'] == 'ip_address')
                assert column['nullable'] is True
                assert db.session.execute(text('SELECT ip_address FROM survey_responses')).scalar_one() is None
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
