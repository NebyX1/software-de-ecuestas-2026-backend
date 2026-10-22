import copy

import pytest

from app.extensions import db
from app.models.survey import ParticipantIdentity, ResponseValue, SurveyResponse
from app.schemas.catalog import CATALOG, MUNICIPALITIES
from test_survey import app, answers, begin, challenge  # noqa: F401

MUNICIPAL_BLOCK = {'municipalityEvaluation': 'buena', 'municipalitySatisfaction': 'conforme', 'municipalityEvolution': 'algo_mejor'}


def residence_paths():
    for locality in CATALOG['LOCALITIES']:
        if locality in ('otra_urbana', 'otra_rural'):
            for membership in CATALOG['MUNICIPALITY_MEMBERSHIP_OPTIONS']:
                yield locality, membership, membership if membership in MUNICIPALITIES else None
        else:
            yield locality, None, locality if locality in MUNICIPALITIES else None


@pytest.mark.parametrize('locality,membership,expected', list(residence_paths()))
def test_api_never_consumes_or_persists_incompatible_branch(app, answers, locality, membership, expected):
    client = app.test_client()
    invitation = begin(client)
    opinions = {**answers, 'locality': locality}
    if membership is not None:
        opinions['municipality'] = membership
    if expected:
        opinions.update(MUNICIPAL_BLOCK)
    payload = {**invitation, **challenge(client, invitation), 'phone': '099123456', 'consent': True,
               'consentVersion': '2026-02', 'answers': opinions}
    invalid = []
    if expected:
        for key in MUNICIPAL_BLOCK:
            missing = copy.deepcopy(opinions)
            del missing[key]
            invalid.append(missing)
    else:
        for key, value in MUNICIPAL_BLOCK.items():
            invalid.append({**opinions, key: value})
    if locality in MUNICIPALITIES:
        for wrong in CATALOG['MUNICIPALITY_MEMBERSHIP_OPTIONS']:
            if wrong != locality:
                invalid.append({**opinions, 'municipality': wrong})
    elif locality in ('otra_urbana', 'otra_rural'):
        missing = copy.deepcopy(opinions)
        del missing['municipality']
        invalid.append(missing)
    else:
        invalid.append({**opinions, 'municipality': 'ns_nc'})
    for key in ('adult', 'lavallejaResident'):
        invalid.append({**opinions, key: 'no'})
    for bad in invalid:
        response = client.post('/api/survey/responses', json={**payload, 'answers': bad})
        assert response.status_code == 422, response.json
    with app.app_context():
        assert SurveyResponse.query.count() == 0
        assert ParticipantIdentity.query.count() == 0
    # Reuse the same verifier: invalid opinions never consumed its proof.
    accepted = client.post('/api/survey/responses', json=payload)
    assert accepted.status_code == 201, accepted.json
    with app.app_context():
        saved = SurveyResponse.query.one()
        assert saved.answers.get('municipality') == (expected or membership)
        assert {key: saved.answers[key] for key in MUNICIPAL_BLOCK if key in saved.answers} == (MUNICIPAL_BLOCK if expected else {})
        projection = ResponseValue.query.filter_by(response_id=saved.id)
        assert projection.filter(ResponseValue.variable.in_(MUNICIPAL_BLOCK)).count() == (3 if expected else 0)
