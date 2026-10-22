import csv
import io
from pathlib import Path

import fakeredis
import pytest
from marshmallow import ValidationError
from sqlalchemy import text, inspect

from app import create_app
from app.extensions import db
from app.models.survey import SurveyResponse
from app.schemas.device import ClientMetadataSchema
from app.services.analytics_service import dashboard_data, iter_csv, parse_filters, response_query
from app.services.device_metadata import capture_device_metadata
from test_survey import app, answers, begin, challenge  # noqa: F401
from test_platform import platform_app, authenticated  # noqa: F401

WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
ANDROID = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36'
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
IPAD_DESKTOP = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15'


@pytest.mark.parametrize('ua,report,expected', [
    (WINDOWS, {}, {'device_type': 'desktop', 'os_family': 'windows', 'os_version': '10 / 11 (no distinguible)', 'browser_family': 'chrome'}),
    (WINDOWS, {'clientHints': {'platform': 'Windows', 'platformVersion': '19.0.0'}}, {'os_version': '11 o posterior'}),
    (ANDROID, {}, {'device_type': 'mobile', 'os_family': 'android', 'os_version': None, 'device_model': None}),
    (ANDROID, {'clientHints': {'platform': 'Android', 'platformVersion': '15.0.0', 'model': 'SM-S928B', 'mobile': True}}, {'device_brand': 'Samsung', 'device_model': 'SM-S928B', 'os_version': '15.0.0'}),
    (IPHONE, {}, {'device_type': 'mobile', 'os_family': 'ios', 'browser_family': 'safari', 'device_brand': 'Apple'}),
    (IPAD_DESKTOP, {'touchPoints': 5}, {'device_type': 'tablet', 'os_family': 'ios', 'os_version': None, 'device_model': 'iPad (estimado)'}),
    (ANDROID + ' [FB_IAB/FB4A;FBAV/500.0.0;]', {}, {'browser_context': 'facebook'}),
    (ANDROID + ' Instagram 355.0.0 Android', {}, {'browser_context': 'instagram'}),
    ('', {}, {'device_type': 'unknown', 'os_family': 'unknown', 'browser_family': 'unknown', 'source': 'not_available'}),
    (WINDOWS, {'clientHints': {'brands': [{'brand': 'Not A Brand', 'version': '99'}, {'brand': 'Google Chrome', 'version': '131'}, {'brand': 'Microsoft Edge', 'version': '131.0.2903.51'}]}}, {'browser_family': 'edge', 'browser_version': '131.0.2903.51'}),
])
def test_detection_and_honest_fallbacks(ua, report, expected):
    metadata = capture_device_metadata(ua, report)
    assert {key: metadata[key] for key in expected} == expected
    assert 'user_agent' not in metadata


@pytest.mark.parametrize('report', [
    {'imei': '123'}, {'screen': {'width': True, 'height': 500}},
    {'screen': {'width': 0, 'height': 500}}, {'viewport': {'width': 500, 'height': 32769}},
    {'clientHints': {'mobile': 1}}, {'clientHints': {'mobile': 'true'}},
    {'clientHints': {'model': 'x' * 129}}, {'clientHints': {'fullVersionList': [{'brand': 'Chrome', 'version': '1'}] * 9}},
    {'touchPoints': False}, {'touchPoints': '1'}, {'touchPoints': 101},
    {'pixelRatio': '1'}, {'pixelRatio': float('nan')}, {'pixelRatio': float('inf')},
    {'timezone': 'x' * 65}, {'language': '<script>'}, {'clientHints': {'platformVersion': 'untrusted'}},
])
def test_optional_report_has_strict_types_and_bounds(report):
    with pytest.raises(ValidationError):
        ClientMetadataSchema().load(report)


def test_persists_metadata_at_submission_and_retry_cannot_replace_it(app, answers):
    client = app.test_client()
    invitation = begin(client)
    payload = {**invitation, **challenge(client, invitation), 'answers': answers, 'phone': '099123456',
               'consent': True, 'consentVersion': '2026-02', 'clientMetadata': {
                   'language': 'es-UY', 'timezone': 'America/Montevideo', 'screen': {'width': 390, 'height': 844},
                   'viewport': {'width': 390, 'height': 700}, 'pixelRatio': 3, 'touchPoints': 5,
                   'clientHints': {'platform': 'Android', 'model': 'SM-S928B', 'platformVersion': '15.0.0', 'mobile': True}}}
    result = client.post('/api/survey/responses', json=payload, headers={'User-Agent': ANDROID})
    assert result.status_code == 201, result.json
    assert set(result.json) == {'status', 'receiptId'}
    payload['clientMetadata'] = {'screen': {'width': 1280, 'height': 900}}
    retry = client.post('/api/survey/responses', json=payload, headers={'User-Agent': WINDOWS})
    assert retry.status_code == 200 and retry.json == result.json
    with app.app_context():
        row = SurveyResponse.query.one()
        assert (row.device_type, row.os_family, row.browser_family) == ('mobile', 'android', 'chrome')
        assert row.device_metadata['device_model'] == 'SM-S928B'
        assert row.device_metadata['screen_width'] == 390
        assert row.device_metadata['language'] == 'es-UY'
        assert row.consent_version == '2026-02'
        assert 'deviceId' not in row.device_metadata and 'phone' not in row.device_metadata
        assert 'clientMetadata' not in row.answers


def test_device_filters_charts_and_safe_csv_include_legacy_rows(app, answers):
    metadata = capture_device_metadata(ANDROID, {'timezone': '=FORMULA()', 'clientHints': {'model': '=BAD()'}})
    with app.app_context():
        db.session.add_all([
            SurveyResponse(survey_id=app.config['SURVEY_ID'], answers=answers, consent_version='2026-01',
                           device_metadata=metadata, device_type='mobile', os_family='android', browser_family='chrome', browser_context='browser'),
            SurveyResponse(survey_id=app.config['SURVEY_ID'], answers=answers, consent_version='2026-01'),
            SurveyResponse(survey_id='other-survey', answers=answers, consent_version='2026-01', device_type='mobile'),
        ])
        db.session.commit()
        filters = parse_filters({'device_type': 'mobile', 'os_family': 'android', 'browser_family': 'chrome', 'browser_context': 'browser'})
        assert response_query(filters).count() == 1
        assert response_query(parse_filters({'device_type': 'not_recorded'})).count() == 1
        data = dashboard_data({})
        assert len(data['distributions']) == 34 and len(data['device_distributions']) == 4
        devices = data['device_distributions'][0]
        assert devices['denominator'] == 2
        assert sum(value['count'] for value in devices['values']) == 2
        assert next(value for value in devices['values'] if value['label'] == 'Celular')['percent'] == 50
        rows = list(csv.DictReader(io.StringIO(''.join(iter_csv(filters)).lstrip('\ufeff'))))
        assert len(rows) == 1 and rows[0]['technical_os_family'] == 'android'
        assert rows[0]['technical_timezone'] == "'=FORMULA()"
        assert rows[0]['technical_device_model'] == "'=BAD()"
        assert not {'phone', 'deviceId', 'device_hash', 'ip_hash', 'token'} & rows[0].keys()
        legacy = list(csv.DictReader(io.StringIO(''.join(iter_csv({'device_type': 'not_recorded'})).lstrip('\ufeff'))))[0]
        assert legacy['technical_device_type'] == ''


@pytest.mark.parametrize('key', ['device_type', 'os_family', 'browser_family', 'browser_context'])
def test_invalid_metadata_filter_rejected(key):
    with pytest.raises(ValidationError):
        parse_filters({key: '<script>'})


def test_metadata_admin_only_and_html_escaped(platform_app, answers):
    with platform_app.app_context():
        row = SurveyResponse(survey_id=platform_app.config['SURVEY_ID'], answers=answers, consent_version='2026-01',
                             device_metadata=capture_device_metadata(ANDROID, {'clientHints': {'model': '<script>alert(1)</script>'}}),
                             device_type='mobile', os_family='android', browser_family='chrome', browser_context='browser')
        legacy = SurveyResponse(survey_id=platform_app.config['SURVEY_ID'], answers=answers, consent_version='2026-01')
        db.session.add_all([row, legacy]); db.session.commit()
        row_id, legacy_id = row.id, legacy.id
    client = platform_app.test_client()
    for path in ('/admin/dashboard', '/admin/responses', f'/admin/responses/{row_id}', '/admin/responses/export.csv'):
        assert client.get(path).status_code == 302
    authenticated(client, platform_app)
    detail = client.get(f'/admin/responses/{row_id}').get_data(as_text=True)
    assert 'Dispositivo y navegador' in detail and 'Android' in detail
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in detail and '<script>alert(1)</script>' not in detail
    assert 'anterior al registro' in client.get(f'/admin/responses/{legacy_id}').get_data(as_text=True)
    assert client.get('/admin/responses?device_type=mobile').status_code == 200
    dashboard = client.get('/admin/dashboard?device_type=mobile').get_data(as_text=True)
    assert dashboard.count('device-chart-card') == 4
    assert client.get('/admin/responses?os_family=bad').status_code == 422


def test_metadata_migration_preserves_existing_opinions(tmp_path):
    instance = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(), 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{(tmp_path / "metadata.sqlite").as_posix()}'})
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    runner = instance.test_cli_runner()
    assert runner.invoke(args=['db', 'upgrade', '-d', migrations, '4d38b91e66a2']).exit_code == 0
    with instance.app_context():
        db.session.execute(text("INSERT INTO survey_responses (id,survey_id,answers,consent_version,consented_at,created_at) VALUES ('old','test','{}','2026-01',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.session.commit()
    for action, target in [('upgrade', 'head'), ('downgrade', '4d38b91e66a2'), ('upgrade', 'head')]:
        result = runner.invoke(args=['db', action, '-d', migrations, target])
        assert result.exit_code == 0, result.output
        with instance.app_context():
            assert db.session.execute(text('SELECT COUNT(*) FROM survey_responses')).scalar_one() == 1
            if action == 'upgrade':
                assert db.session.execute(text('SELECT device_metadata FROM survey_responses')).scalar_one() is None
                assert len([i for i in inspect(db.engine).get_indexes('survey_responses') if i['name'].startswith('ix_response_')]) == 4
