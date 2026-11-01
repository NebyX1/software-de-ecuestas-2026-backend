"""Trial exports exercise real connection metadata without persisting answers."""
import csv
import io
from unittest.mock import Mock

import pytest
from sqlalchemy import event
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import db
from app.models.survey import ParticipantIdentity, ResponseValue, SurveyInvitation, SurveyResponse
from app.services.challenge_service import consume_challenge
from test_platform import platform_app  # noqa: F401
from test_simulation import access, payload
from test_survey import answers  # noqa: F401


def csv_rows(response):
    return list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip('\ufeff'))))


def row_counts():
    return [model.query.count() for model in (SurveyInvitation, SurveyResponse, ParticipantIdentity, ResponseValue)]


@pytest.mark.parametrize(('address', 'expected'), [
    ('198.51.100.27', '198.51.100.27'),
    ('2001:0DB8:0001:0002:0000:0000:ABCD:0042', '2001:db8:1:2::abcd:42'),
    ('::ffff:198.51.100.27', '198.51.100.27'),
])
def test_trial_csv_uses_actual_export_connection_ip_without_sql_writes(platform_app, answers, address, expected):
    client = platform_app.test_client()
    run = access(client, platform_app)
    data = payload(client, run, answers)
    with platform_app.app_context():
        before = row_counts()
        engine = db.engine
    writes = []

    def reject_writes(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'REPLACE ')):
            writes.append(statement.split(None, 1)[0])
            pytest.fail('A simulation export attempted a SQL write')

    event.listen(engine, 'before_cursor_execute', reject_writes)
    try:
        result = client.post('/api/simulation/export.csv', json=data,
                             environ_overrides={'REMOTE_ADDR': address})
        assert result.status_code == 200, result.get_data(as_text=True)
        records = csv_rows(result)
        assert len(records) == 1
        assert records[0]['ip_address'] == expected
        assert records[0]['id'].startswith('SIMULACION-')
        assert result.mimetype == 'text/csv'
        assert 'no-store' in result.headers['Cache-Control']
        with platform_app.app_context():
            assert row_counts() == before
        assert not writes
    finally:
        event.remove(engine, 'before_cursor_execute', reject_writes)


@pytest.mark.parametrize(('hops', 'expected'), [(0, '10.20.30.40'), (1, '203.0.113.77')])
def test_trial_export_uses_only_the_configured_trusted_proxy(platform_app, answers, hops, expected):
    base = platform_app.wsgi_app
    while isinstance(base, ProxyFix):
        base = base.app
    platform_app.wsgi_app = ProxyFix(base, x_for=hops, x_proto=0)
    client = platform_app.test_client()
    run = access(client, platform_app)
    data = payload(client, run, answers)
    result = client.post('/api/simulation/export.csv', json=data,
        environ_overrides={'REMOTE_ADDR': '10.20.30.40'}, headers={
            'X-Forwarded-For': '198.51.100.99, 203.0.113.77',
            'X-Real-IP': '198.51.100.88', 'CF-Connecting-IP': '198.51.100.66'})
    assert result.status_code == 200, result.get_data(as_text=True)
    assert csv_rows(result)[0]['ip_address'] == expected
    with platform_app.app_context():
        assert row_counts() == [0, 0, 0, 0]


@pytest.mark.parametrize('address', [None, '', 'not-an-ip', '198.51.100.27:443', 'fe80::1%eth0'])
def test_invalid_trial_ip_does_not_consume_challenge(platform_app, answers, monkeypatch, address):
    client = platform_app.test_client()
    run = access(client, platform_app)
    data = payload(client, run, answers)
    consume = Mock(wraps=consume_challenge)
    monkeypatch.setattr('app.services.simulation_service.consume_challenge', consume)
    result = client.post('/api/simulation/export.csv', json=data,
                         environ_overrides={'REMOTE_ADDR': address})
    assert result.status_code == 503 and result.json['code'] == 'service_unavailable'
    consume.assert_not_called()
    with platform_app.app_context():
        assert row_counts() == [0, 0, 0, 0]
    retried = client.post('/api/simulation/export.csv', json=data,
                          environ_overrides={'REMOTE_ADDR': '203.0.113.7'})
    assert retried.status_code == 200
    assert csv_rows(retried)[0]['ip_address'] == '203.0.113.7'
    assert consume.call_count == 1


def test_trial_json_cannot_supply_the_csv_ip(platform_app, answers):
    client = platform_app.test_client()
    run = access(client, platform_app)
    data = payload(client, run, answers)
    rejected = client.post('/api/simulation/export.csv',
        json={**data, 'ip_address': '198.51.100.99'}, environ_overrides={'REMOTE_ADDR': '203.0.113.8'})
    assert rejected.status_code == 422
    exported = client.post('/api/simulation/export.csv', json=data,
                            environ_overrides={'REMOTE_ADDR': '203.0.113.8'})
    assert exported.status_code == 200
    assert csv_rows(exported)[0]['ip_address'] == '203.0.113.8'
    with platform_app.app_context():
        assert row_counts() == [0, 0, 0, 0]
