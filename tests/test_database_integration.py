"""Race/regression tests against a migrated, dedicated MariaDB database.

Opt-in: TEST_DATABASE_URL=mysql+pymysql://.../dedicated_test_database
No DROP/create_all is used: migrations must have provisioned the schema first.
Each test uses its own survey ID and removes only that survey's records.
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import inspect

from app import create_app
from app.extensions import db
from app.models.survey import ParticipantIdentity, ResponseValue, SurveyInvitation, SurveyResponse
from app.schemas.catalog import AREAS


@pytest.fixture
def database_app():
    uri = os.environ.get('TEST_DATABASE_URL')
    if not uri:
        pytest.skip('Set TEST_DATABASE_URL to run real MariaDB concurrency tests')
    if not uri.startswith(('mysql+pymysql://', 'mariadb+mariadbconnector://')):
        pytest.fail('Integration tests require MariaDB, not SQLite')
    survey_id = f'integration-{uuid4()}'
    app = create_app('testing', {
        'SQLALCHEMY_DATABASE_URI': uri,
        'SURVEY_ID': survey_id,
        'SURVEY_ENFORCE_IP_UNIQUENESS': False,
        'MAIL_DEFAULT_SENDER': 'test@example.org',
        'REDIS_CLIENT': Redis.from_url(os.environ.get('TEST_REDIS_URL', os.environ.get('REDIS_URL', 'redis://127.0.0.1:6399/0'))),
        'SQLALCHEMY_ENGINE_OPTIONS': {'pool_pre_ping': True, 'pool_size': 12, 'max_overflow': 4},
    })
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
        assert {'alembic_version', 'users', 'two_factor_codes', 'survey_invitations',
                'participant_identities', 'survey_responses', 'response_values'} <= tables
    yield app
    with app.app_context():
        ids = db.select(SurveyResponse.id).where(SurveyResponse.survey_id == survey_id)
        db.session.execute(db.delete(ResponseValue).where(ResponseValue.response_id.in_(ids)))
        db.session.execute(db.delete(SurveyResponse).where(SurveyResponse.survey_id == survey_id))
        db.session.execute(db.delete(SurveyInvitation).where(SurveyInvitation.survey_id == survey_id))
        db.session.execute(db.delete(ParticipantIdentity).where(ParticipantIdentity.survey_id == survey_id))
        db.session.commit()
        db.session.remove()
        db.engine.dispose()


def answers():
    return {
        'adult': 'si', 'lavallejaResident': 'si', 'locality': 'minas',
        'gender': 'ns_nc', 'ageRange': '35_44', 'voted2025': 'pnr',
        'generalEvaluation': 'buena', 'generalSatisfaction': 'conforme',
        'managementEvolution': 'aprox_igual',
        'areas': {area: 'ns_nc' for area in AREAS},
        'concerns': ['ns_nc'], 'priorities': ['ns_nc'],
        'openComment': 'Prueba de concurrencia contra MariaDB.',
    }


def invitation(app, client=None, device=None, phone='099123456'):
    client = client or app.test_client()
    device = device or str(uuid4())
    response = client.post('/api/survey/links', json={'deviceId': device})
    assert response.status_code == 201, response.get_json()
    data = {
        'token': response.json['token'], 'deviceId': device,
        'phone': phone, 'answers': answers(), 'consent': True, 'consentVersion': '2026-01',
    }
    verification = client.post('/api/survey/challenge', json={'token': data['token'], 'deviceId': device})
    assert verification.status_code == 200, verification.get_json()
    operands = re.findall(r'\d+', verification.json['question'])
    assert len(operands) == 2
    data.update(challengeId=verification.json['challengeId'], challengeAnswer=str(sum(map(int, operands))), website='')
    return client, data


def race(app, participants):
    gate = Barrier(len(participants))

    def submit(pair):
        client, data = pair
        gate.wait(timeout=15)
        result = client.post('/api/survey/responses', json=data)
        return result.status_code, result.get_json()

    with ThreadPoolExecutor(max_workers=len(participants)) as workers:
        return list(workers.map(submit, participants))


def assert_single_response(app, expected_claims):
    with app.app_context():
        assert SurveyResponse.query.filter_by(survey_id=app.config['SURVEY_ID']).count() == 1
        assert ParticipantIdentity.query.filter_by(survey_id=app.config['SURVEY_ID']).count() == expected_claims
        assert SurveyInvitation.query.filter_by(survey_id=app.config['SURVEY_ID']).filter(SurveyInvitation.consumed_at.is_not(None)).count() == 1


def test_parallel_same_submission_has_one_persisted_response(database_app):
    app = database_app
    client, data = invitation(app)
    cookies = list(client._cookies.values())
    participants = []
    for _ in range(8):
        worker = app.test_client()
        for cookie in cookies:
            worker.set_cookie(cookie.key, cookie.value, domain=cookie.domain)
        participants.append((worker, data))
    results = race(app, participants)
    assert sum(status == 201 for status, _ in results) == 1, results
    assert all(status in (200, 201) for status, _ in results), results
    assert len({body['receiptId'] for _, body in results}) == 1
    assert_single_response(app, 3)


def test_two_browsers_racing_same_phone_get_one_response(database_app):
    app = database_app
    results = race(app, [invitation(app), invitation(app)])
    assert sorted(status for status, _ in results) == [201, 409], results
    assert_single_response(app, 3)


def test_two_links_racing_same_device_get_one_response(database_app):
    app = database_app
    device = str(uuid4())
    results = race(app, [invitation(app, device=device), invitation(app, device=device, phone='098123456')])
    assert sorted(status for status, _ in results) == [201, 409], results
    assert_single_response(app, 3)


def test_two_browsers_racing_same_ip_get_one_response(database_app):
    app = database_app
    app.config['SURVEY_ENFORCE_IP_UNIQUENESS'] = True
    results = race(app, [invitation(app), invitation(app, phone='098123456')])
    assert sorted(status for status, _ in results) == [201, 409], results
    assert_single_response(app, 4)


def test_selected_policy_accepts_distinct_people_on_shared_ip(database_app):
    app = database_app
    results = race(app, [invitation(app), invitation(app, phone='098123456')])
    assert [status for status, _ in results] == [201, 201], results
    with app.app_context():
        assert SurveyResponse.query.filter_by(survey_id=app.config['SURVEY_ID']).count() == 2
        assert ParticipantIdentity.query.filter_by(survey_id=app.config['SURVEY_ID'], kind='ip').count() == 0


def test_all_26_residential_paths_are_persisted_with_their_own_municipality(database_app):
    from test_conditional_flow import residence_paths, MUNICIPAL_BLOCK
    from app.services.analytics_service import dashboard_data, iter_csv
    import csv
    import io
    app = database_app
    paths = list(residence_paths())
    for index, (locality, membership, expected) in enumerate(paths):
        client, data = invitation(app, phone=f'09{index:07d}')
        opinions = {**answers(), 'locality': locality, 'openComment': f'Recorrido residencial {index}.'}
        if membership is not None:
            opinions['municipality'] = membership
        if expected:
            opinions.update(MUNICIPAL_BLOCK)
        data['answers'] = opinions
        response = client.post('/api/survey/responses', json=data)
        assert response.status_code == 201, response.json
        with app.app_context():
            stored = SurveyResponse.query.filter_by(survey_id=app.config['SURVEY_ID']).filter(
                SurveyResponse.answers['openComment'].as_string() == opinions['openComment']).one()
            assert stored.answers.get('municipality') == (expected or membership)
            assert {key for key in MUNICIPAL_BLOCK if key in stored.answers} == (set(MUNICIPAL_BLOCK) if expected else set())
    with app.app_context():
        assert len(paths) == 26
        assert SurveyResponse.query.filter_by(survey_id=app.config['SURVEY_ID']).count() == 26
        charts = dashboard_data({})
        for field in MUNICIPAL_BLOCK:
            chart = next(item for item in charts['distributions'] if item['key'] == field)
            assert chart['denominator'] == 18  # 6 direct + 6 urban + 6 rural; never Minas/NsNc/nonmembers.
        rows = list(csv.DictReader(io.StringIO(''.join(iter_csv({})).lstrip('\ufeff'))))
        for row in rows:
            municipal = row['municipality'] in ('solis_de_mataojo', 'jose_pedro_varela', 'mariscala', 'zapican', 'jose_batlle_y_ordonez', 'piraraja')
            assert all(bool(row[key]) == municipal for key in MUNICIPAL_BLOCK)
        for municipality in ('solis_de_mataojo', 'jose_pedro_varela', 'mariscala', 'zapican', 'jose_batlle_y_ordonez', 'piraraja'):
            selection = dashboard_data({'municipality': municipality})
            assert selection['total'] == 3
            for field in MUNICIPAL_BLOCK:
                chart = next(item for item in selection['distributions'] if item['key'] == field)
                assert chart['denominator'] == 3


def test_csv_stream_crosses_250_rows_without_loss_after_real_submissions(database_app):
    from scenarios.csv_export import verify_large_csv
    report = verify_large_csv(database_app)
    assert report['submitted'] == report['csvRows'] == 261
