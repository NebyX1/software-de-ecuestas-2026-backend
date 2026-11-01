"""Submission addresses are available only through authenticated admin views."""
import csv
import io

from app.extensions import db
from app.models.survey import SurveyResponse
from app.services.analytics_service import csv_columns
from test_platform import platform_app, authenticated  # noqa: F401
from test_survey import app, answers, begin, challenge  # noqa: F401
from test_simulation import access, payload


def read_csv(response):
    return list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip('\ufeff'))))


def test_admin_list_detail_and_csv_include_exact_ip_with_legacy_empty(platform_app, answers):
    with platform_app.app_context():
        rows = [SurveyResponse(survey_id=platform_app.config['SURVEY_ID'], answers=answers,
                               consent_version='2026-02', ip_address=address)
                for address in ('203.0.113.19', '2001:db8:1234:5678::9', None)]
        db.session.add_all(rows)
        db.session.commit()
        identifiers = [row.id for row in rows]

    client = platform_app.test_client()
    paths = ['/admin/responses', '/admin/responses/export.csv',
             *[f'/admin/responses/{identifier}' for identifier in identifiers]]
    for path in paths:
        blocked = client.get(path)
        assert blocked.status_code == 302
        assert b'203.0.113.19' not in blocked.data
        assert b'2001:db8:1234:5678::9' not in blocked.data

    authenticated(client, platform_app)
    listing = client.get('/admin/responses').get_data(as_text=True)
    assert 'IP de envío' in listing
    assert '203.0.113.19' in listing and '2001:db8:1234:5678::9' in listing
    assert 'Sin registro (respuesta anterior)' in listing
    for identifier, expected in zip(identifiers, ['203.0.113.19', '2001:db8:1234:5678::9', 'Sin registro (respuesta anterior)']):
        detail = client.get(f'/admin/responses/{identifier}').get_data(as_text=True)
        assert 'IP de envío' in detail and expected in detail

    exported = client.get('/admin/responses/export.csv')
    assert exported.status_code == 200
    assert exported.headers['Content-Type'].startswith('text/csv')
    records = {row['id']: row for row in read_csv(exported)}
    assert csv_columns()[:4] == ['id', 'created_at_utc', 'ip_address', 'consent_version']
    assert [records[identifier]['ip_address'] for identifier in identifiers] == ['203.0.113.19', '2001:db8:1234:5678::9', '']
    assert not {'phone', 'deviceId', 'device_hash', 'browser_hash', 'ip_hash', 'token'} & records[identifiers[0]].keys()


def test_simulation_csv_has_blank_ip_and_no_persisted_opinions(platform_app, answers):
    client = platform_app.test_client()
    run = access(client, platform_app)
    data = payload(client, run, answers)
    with platform_app.app_context():
        count = SurveyResponse.query.count()
    exported = client.post('/api/simulation/export.csv', json=data,
                           environ_overrides={'REMOTE_ADDR': '203.0.113.77'})
    assert exported.status_code == 200
    records = read_csv(exported)
    assert len(records) == 1 and records[0]['ip_address'] == ''
    assert '203.0.113.77' not in exported.get_data(as_text=True)
    with platform_app.app_context():
        assert SurveyResponse.query.count() == count


def test_public_submission_does_not_disclose_stored_ip(app, answers):
    client = app.test_client()
    invitation = begin(client, ip='203.0.113.42')
    verified = challenge(client, invitation, ip='203.0.113.42')
    submitted = client.post('/api/survey/responses', json={
        **invitation, **verified, 'phone': '099123456', 'answers': answers,
        'consent': True, 'consentVersion': '2026-02',
    }, environ_overrides={'REMOTE_ADDR': '203.0.113.42'})
    assert submitted.status_code == 201
    assert set(submitted.json) == {'status', 'receiptId'}
    assert '203.0.113.42' not in submitted.get_data(as_text=True)
    with app.app_context():
        assert SurveyResponse.query.one().ip_address == '203.0.113.42'
