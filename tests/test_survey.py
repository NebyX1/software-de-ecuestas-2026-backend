import copy
import csv
import io
import re
import fakeredis
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from marshmallow import ValidationError

from app import create_app
from app.extensions import db
from app.models.survey import ParticipantIdentity, ResponseValue, SurveyInvitation, SurveyResponse
from app.schemas.catalog import AREAS
from app.schemas.survey import AnswersSchema, normalize_phone
from app.services.analytics_service import dashboard_data, iter_csv, parse_filters, response_query
from app.services.survey_service import purge_invitation_metadata


@pytest.fixture
def app():
    instance = create_app('testing', {'REDIS_CLIENT': fakeredis.FakeRedis(), 'SURVEY_ENFORCE_IP_UNIQUENESS': True})
    with instance.app_context():
        db.create_all()
    yield instance
    with instance.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def answers():
    return {
        'adult': 'si', 'lavallejaResident': 'si', 'locality': 'minas',
        'gender': 'femenino', 'ageRange': '23_34', 'voted2025': 'pnr',
        'generalEvaluation': 'buena', 'generalSatisfaction': 'conforme', 'managementEvolution': 'aprox_igual',
        'areas': {key: 'ns_nc' for key in AREAS}, 'concerns': ['costo_vida'], 'priorities': ['empleo'],
        'openComment': 'Más oportunidades para jóvenes.',
    }


def begin(client, ip='203.0.113.10', device=None):
    device = device or str(uuid4())
    response = client.post('/api/survey/links', json={'deviceId': device}, environ_overrides={'REMOTE_ADDR': ip})
    assert response.status_code == 201, response.get_json()
    return {'token': response.json['token'], 'deviceId': device}


def challenge(client, invitation, ip='203.0.113.10'):
    result = client.post('/api/survey/challenge', json=invitation, environ_overrides={'REMOTE_ADDR': ip})
    assert result.status_code == 200, result.get_json()
    numbers = re.findall(r'[0-9]+', result.json['question'])
    return {'challengeId': result.json['challengeId'], 'challengeAnswer': str(sum(map(int, numbers))), 'website': ''}


def submit(client, invitation, answers, phone='099123456', ip='203.0.113.10'):
    cache = getattr(client, '_survey_test_challenges', {})
    if invitation['token'] not in cache:
        cache[invitation['token']] = challenge(client, invitation, ip)
        client._survey_test_challenges = cache
    verified = cache[invitation['token']]
    return client.post('/api/survey/responses', json={**invitation, **verified, 'phone': phone, 'answers': answers,
                       'consent': True, 'consentVersion': '2026-01'}, environ_overrides={'REMOTE_ADDR': ip})


def test_real_submission_idempotent_retry_and_new_link_block(app, answers):
    client = app.test_client()
    invitation = begin(client)
    first = submit(client, invitation, answers)
    assert first.status_code == 201
    second = submit(client, invitation, answers)
    assert second.status_code == 200
    assert second.json == first.json
    changed = copy.deepcopy(answers)
    changed['openComment'] = 'Otro comentario'
    assert submit(client, invitation, changed).json['code'] == 'link_used'
    status = client.post('/api/survey/session', json=invitation)
    assert status.json['status'] == 'completed'
    duplicate = client.post('/api/survey/links', json={'deviceId': invitation['deviceId']})
    assert duplicate.status_code == 409
    with app.app_context():
        opinion = SurveyResponse.query.one()
        assert opinion.id != first.json['receiptId']
        assert 'phone' not in opinion.answers
        assert ParticipantIdentity.query.count() == 4
        assert ResponseValue.query.count() == 29


def test_shared_link_rejected_before_and_after_use(app, answers):
    owner, stranger = app.test_client(), app.test_client()
    invitation = begin(owner)
    copied = stranger.post('/api/survey/session', json=invitation)
    assert copied.status_code == 403 and copied.json['code'] == 'link_bound'
    # Copying the device UUID too is insufficient without the HttpOnly cookie.
    submit(owner, invitation, answers)
    consumed = stranger.post('/api/survey/session', json=invitation)
    assert consumed.status_code == 409 and consumed.json['code'] == 'link_used'
    # Same browser with another device value also fails binding.
    assert owner.post('/api/survey/session', json={**invitation, 'deviceId': str(uuid4())}).status_code == 409


def test_expiration_and_unknown_token(app):
    client = app.test_client()
    invitation = begin(client)
    with app.app_context():
        row = SurveyInvitation.query.one()
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.session.commit()
    assert client.post('/api/survey/session', json=invitation).status_code == 410
    assert client.post('/api/survey/session', json={**invitation, 'token': 'x' * 43}).status_code == 404


def test_unique_phone_and_ip_are_durable(app, answers):
    first = app.test_client()
    invitation = begin(first)
    assert submit(first, invitation, answers).status_code == 201
    same_network = app.test_client()
    response = same_network.post('/api/survey/links', json={'deviceId': str(uuid4())}, environ_overrides={'REMOTE_ADDR': '203.0.113.10'})
    assert response.status_code == 409
    other_network = app.test_client()
    other = begin(other_network, ip='203.0.113.11')
    response = submit(other_network, other, answers, phone='+59899123456', ip='203.0.113.11')
    assert response.status_code == 409
    with app.app_context():
        assert SurveyResponse.query.count() == 1


def test_relaxed_ip_policy_still_blocks_device_and_phone(app, answers):
    app.config['SURVEY_ENFORCE_IP_UNIQUENESS'] = False
    first, second = app.test_client(), app.test_client()
    one, two = begin(first), begin(second)
    assert submit(first, one, answers).status_code == 201
    assert submit(second, two, answers, phone='098123456').status_code == 201
    with app.app_context():
        assert ParticipantIdentity.query.filter_by(kind='ip').count() == 0


def test_default_policy_uses_ip_for_frequency_without_permanent_exclusion(monkeypatch):
    from app.config import build_config
    monkeypatch.delenv('SURVEY_ENFORCE_IP_UNIQUENESS', raising=False)
    settings = build_config('testing')
    assert settings['SURVEY_ENFORCE_IP_UNIQUENESS'] is False
    assert settings['SURVEY_LINK_IP_LIMIT'] and settings['SURVEY_CHALLENGE_IP_LIMIT'] and settings['SURVEY_RESPONSE_IP_LIMIT']


def test_https_csrf_accepts_only_same_origin_referer(app):
    app.config['WTF_CSRF_ENABLED'] = True
    client = app.test_client()
    csrf = client.get('/api/csrf', base_url='https://localhost').json['csrf_token']
    headers = {'X-CSRFToken': csrf}
    data = {'deviceId': str(uuid4())}
    assert client.post('/api/survey/links', base_url='https://localhost', json=data, headers=headers).status_code == 400
    assert client.post('/api/survey/links', base_url='https://localhost', json=data,
                       headers={**headers, 'Referer': 'https://untrusted.example.org/'}).status_code == 400
    result = client.post('/api/survey/links', base_url='https://localhost', json=data,
                         headers={**headers, 'Referer': 'https://localhost/participar'})
    assert result.status_code == 201, result.json


@pytest.mark.parametrize('patch', [
    {'adult': 'no'}, {'lavallejaResident': 'no'}, {'locality': 'unknown'},
    {'gender': 1}, {'voted2025': 'si'}, {'party2025': 'pnr'},
    {'areas': {'social': 'buena'}}, {'concerns': ['costo_vida', 'costo_vida']},
    {'concerns': ['ninguno', 'costo_vida']}, {'concerns': ['otro']},
    {'concernOther': 'Texto sin otro'}, {'priorities': ['ns_nc', 'empleo']},
    {'priorities': ['empleo', 'empleo']}, {'openComment': '   '},
    {'openComment': 'x' * 751}, {'municipalityEvaluation': 'buena'}, {'unknownField': True},
])
def test_strict_survey_schema_rejects_invalid_or_inconsistent_answers(answers, patch):
    with pytest.raises(ValidationError):
        AnswersSchema().load({**answers, **patch})


def test_conditional_municipal_flow(answers):
    municipal = {**answers, 'locality': 'mariscala', 'municipalityEvaluation': 'buena',
                 'municipalitySatisfaction': 'conforme', 'municipalityEvolution': 'algo_mejor'}
    assert AnswersSchema().load(municipal)['municipality'] == 'mariscala'
    with pytest.raises(ValidationError):
        AnswersSchema().load({**municipal, 'municipality': 'zapican'})
    for locality in ('otra_urbana', 'otra_rural'):
        with pytest.raises(ValidationError):
            AnswersSchema().load({**answers, 'locality': locality})
        valid = AnswersSchema().load({**answers, 'locality': locality, 'municipality': 'no_pertenece'})
        assert valid['municipality'] == 'no_pertenece'


@pytest.mark.parametrize('phone', ['099123456', '099 123 456', '+598 99 123 456', '59899123456'])
def test_uruguay_phone_canonicalization(phone):
    assert normalize_phone(phone) == '+59899123456'


@pytest.mark.parametrize('phone', ['123456', '+54999123456', '+598099123456', '0991234567', '<script>', '099١٢٣٤٥٦'])
def test_invalid_phone(phone):
    with pytest.raises(ValidationError):
        normalize_phone(phone)


def test_unknown_fields_and_literal_consent(app, answers):
    client = app.test_client()
    assert client.post('/api/survey/links', json={'deviceId': str(uuid4()), 'fbclid': 'untrusted'}).status_code == 422
    invitation = begin(client)
    response = client.post('/api/survey/responses', json={**invitation, 'answers': answers, 'phone': '099123456', 'consent': 1, 'consentVersion': '2026-01'})
    assert response.status_code == 422
    assert client.post('/api/survey/session', json=[]).status_code == 422


def test_csv_filters_formula_safety_and_analytics_denominators(app, answers):
    client = app.test_client()
    invitation = begin(client)
    answers['openComment'] = '=HYPERLINK("https://evil.invalid")'
    answers['concerns'] = ['costo_vida', 'falta_empleo']
    assert submit(client, invitation, answers).status_code == 201
    with app.app_context():
        data = dashboard_data(parse_filters({'gender': 'femenino'}))
        assert data['total'] == 1 and data['total_all'] == 1
        concerns = next(d for d in data['distributions'] if d['key'] == 'concerns')
        assert concerns['denominator'] == 1 and concerns['multiple']
        assert sum(v['count'] for v in concerns['values']) == 2
        assert len(data['distributions']) == 34
        assert response_query(parse_filters({'areas.social': 'ns_nc'})).count() == 1
        assert response_query(parse_filters({'areas.social': 'buena'})).count() == 0
        exported = ''.join(iter_csv({})).lstrip('\ufeff')
        rows = list(csv.DictReader(io.StringIO(exported)))
        assert rows[0]['openComment'].startswith("'=")
        assert 'phone' not in exported and 'ip_hash' not in exported
        assert '099123456' not in exported
        assert len(list(csv.DictReader(io.StringIO(''.join(iter_csv({'gender': 'masculino'})).lstrip('\ufeff'))))) == 0


def test_date_filters_are_montevideo_dates_inclusive(app, answers):
    with app.app_context():
        db.session.add_all([
            SurveyResponse(survey_id=app.config['SURVEY_ID'], answers=answers, consent_version='2026-01', created_at=datetime(2026, 10, 21, 2, 59)),
            SurveyResponse(survey_id=app.config['SURVEY_ID'], answers=answers, consent_version='2026-01', created_at=datetime(2026, 10, 21, 3, 0)),
            SurveyResponse(survey_id=app.config['SURVEY_ID'], answers=answers, consent_version='2026-01', created_at=datetime(2026, 10, 22, 2, 59)),
            SurveyResponse(survey_id=app.config['SURVEY_ID'], answers=answers, consent_version='2026-01', created_at=datetime(2026, 10, 22, 3, 0)),
        ])
        db.session.commit()
        filters = parse_filters({'date_from': '2026-10-21', 'date_to': '2026-10-21'})
        assert response_query(filters).count() == 2
        with pytest.raises(ValidationError):
            parse_filters({'date_from': '2026-10-22', 'date_to': '2026-10-21'})


def test_cleanup_preserves_durable_claims_and_opinions(app, answers):
    client = app.test_client()
    invitation = begin(client)
    submit(client, invitation, answers)
    with app.app_context():
        SurveyInvitation.query.one().consumed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        db.session.commit()
        result = purge_invitation_metadata()
        assert result['invitations_deleted'] == 1
        assert SurveyResponse.query.count() == 1
        assert ParticipantIdentity.query.count() == 4


def test_csrf_protects_public_posts(app):
    app.config['WTF_CSRF_ENABLED'] = True
    client = app.test_client()
    payload = {'deviceId': str(uuid4())}
    denied = client.post('/api/survey/links', json=payload)
    assert denied.status_code == 400
    token = client.get('/api/csrf').json['csrf_token']
    allowed = client.post('/api/survey/links', json=payload, headers={'X-CSRFToken': token})
    assert allowed.status_code == 201
