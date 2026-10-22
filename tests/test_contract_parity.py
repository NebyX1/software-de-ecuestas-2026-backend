"""Complete conditional questionnaire contract, runnable in the standalone API.

``contract_cases()`` also supplies the frontend runtime parity audit. These
examples cover every locality/membership/electoral branch and allowed option.
They contain fictional opinions only and require no network or database.
"""
import copy

import pytest
from marshmallow import ValidationError

from app.schemas.catalog import AREAS, CATALOG, MUNICIPALITIES
from app.schemas.survey import AnswersSchema


def _base():
    return {
        'adult': 'si', 'lavallejaResident': 'si', 'locality': 'minas',
        'gender': 'ns_nc', 'ageRange': '35_44', 'voted2025': 'pnr',
        'generalEvaluation': 'buena', 'generalSatisfaction': 'conforme',
        'managementEvolution': 'aprox_igual',
        'areas': {key: 'ns_nc' for key in AREAS},
        'concerns': ['ns_nc'], 'priorities': ['ns_nc'], 'openComment': 'Comentario de prueba del contrato.',
    }


def _municipal_answers():
    return {'municipalityEvaluation': 'buena', 'municipalitySatisfaction': 'conforme',
            'municipalityEvolution': 'aprox_igual'}


def contract_cases():
    cases = []

    def add(name, answers, valid=True, municipal=False, membership=False):
        cases.append({'name': name, 'answers': copy.deepcopy(answers), 'valid': valid,
                      'municipalStep': municipal, 'membershipStep': membership})

    residence_variants = []
    for locality in CATALOG['LOCALITIES']:
        if locality in ('otra_urbana', 'otra_rural'):
            for municipality in CATALOG['MUNICIPALITY_MEMBERSHIP_OPTIONS']:
                state = {**_base(), 'locality': locality, 'municipality': municipality}
                known = municipality in MUNICIPALITIES
                if known:
                    state.update(_municipal_answers())
                residence_variants.append((locality + '-' + municipality, state, known, True))
        else:
            state = {**_base(), 'locality': locality}
            known = locality in MUNICIPALITIES
            if known:
                state.update(_municipal_answers())
            residence_variants.append((locality, state, known, False))
    for name, state, municipal, membership in residence_variants:
        for vote in ('no', 'no_recuerdo', 'pnr'):
            add(name + '-vote-' + vote, {**state, 'voted2025': vote}, municipal=municipal, membership=membership)
        for party in CATALOG['PARTY_2025_OPTIONS']:
            add(name + '-party-' + party, {**state, 'voted2025': 'si', 'party2025': party},
                municipal=municipal, membership=membership)

    scalar_options = {
        'gender': 'GENDER_OPTIONS', 'ageRange': 'AGE_RANGE_OPTIONS',
        'generalEvaluation': 'GENERAL_EVALUATION_OPTIONS',
        'generalSatisfaction': 'CONFORMITY_OPTIONS', 'managementEvolution': 'EVOLUTION_OPTIONS',
    }
    for field, catalog in scalar_options.items():
        for value in CATALOG[catalog]:
            add(field + '-' + value, {**_base(), field: value})
    for area in AREAS:
        for value in CATALOG['GENERAL_EVALUATION_OPTIONS']:
            state = _base()
            state['areas'][area] = value
            add('area-' + area + '-' + value, state)
    for value in CATALOG['CONCERN_OPTIONS']:
        state = {**_base(), 'concerns': [value]}
        if value == 'otro':
            state['concernOther'] = 'Otro problema de prueba'
        add('concern-' + value, state)
    for value in CATALOG['PRIORITY_OPTIONS']:
        add('priority-' + value, {**_base(), 'priorities': [value]})
    add('three-concerns', {**_base(), 'concerns': ['costo_vida', 'falta_empleo', 'otro'], 'concernOther': 'Otra preocupación'})
    add('three-priorities', {**_base(), 'priorities': ['empleo', 'obras', 'otro']})
    add('comment-maximum', {**_base(), 'openComment': 'a' * 750})
    add('trimmed-comments', {**_base(), 'openComment': '  Comentario con espacios  '})
    add('concern-other-maximum', {**_base(), 'concerns': ['otro'], 'concernOther': 'a' * 150})

    invalid_patches = [
        ('ineligible-age', {'adult': 'no'}), ('ineligible-residence', {'lavallejaResident': 'no'}),
        ('unknown-locality', {'locality': 'inventada'}), ('age-not-string', {'ageRange': 35}),
        ('vote-without-party', {'voted2025': 'si'}), ('hidden-party', {'party2025': 'pnr'}),
        ('null-party', {'party2025': None}), ('missing-membership', {'locality': 'otra_urbana'}),
        ('rural-missing-membership', {'locality': 'otra_rural'}),
        ('direct-missing-evaluation', {'locality': 'mariscala'}),
        ('other-missing-evaluation', {'locality': 'otra_rural', 'municipality': 'zapican'}),
        ('hidden-municipality', {'municipality': 'mariscala'}),
        ('extra-municipal-block', _municipal_answers()),
        ('no-municipality-extra-evaluation', {'locality': 'otra_urbana', 'municipality': 'no_seguro', **_municipal_answers()}),
        ('missing-areas', {'areas': {}}), ('unknown-area', {'areas': {**_base()['areas'], 'inventada': 'buena'}}),
        ('concerns-empty', {'concerns': []}), ('concern-other-missing', {'concerns': ['otro']}),
        ('concern-other-blank', {'concerns': ['otro'], 'concernOther': '   '}),
        ('concern-other-long', {'concerns': ['otro'], 'concernOther': 'a' * 151}),
        ('concern-other-hidden', {'concernOther': 'Texto oculto'}),
        ('concerns-exclusive', {'concerns': ['ninguno', 'ns_nc']}),
        ('concerns-none-exclusive', {'concerns': ['ninguno', 'costo_vida']}),
        ('concerns-repeated', {'concerns': ['costo_vida', 'costo_vida']}),
        ('concerns-limit', {'concerns': ['costo_vida', 'falta_empleo', 'seguridad', 'vivienda']}),
        ('concerns-unknown', {'concerns': ['inventada']}),
        ('priorities-empty', {'priorities': []}), ('priorities-exclusive', {'priorities': ['ns_nc', 'empleo']}),
        ('priorities-repeated', {'priorities': ['empleo', 'empleo']}),
        ('priorities-limit', {'priorities': ['empleo', 'obras', 'limpieza', 'camineria']}),
        ('priorities-unknown', {'priorities': ['inventada']}),
        ('comment-blank', {'openComment': ' \t\n '}), ('comment-long', {'openComment': 'a' * 751}),
        ('comment-null', {'openComment': None}), ('unknown-field', {'admin': True}),
    ]
    for name, patch in invalid_patches:
        add(name, {**_base(), **patch}, valid=False)

    # Independent truth table: every locality, every explicit membership (or
    # absence), and all 8 subsets of the three municipal questions.
    municipal_fields = tuple(_municipal_answers())
    for locality in CATALOG['LOCALITIES']:
        for membership in (None, *CATALOG['MUNICIPALITY_MEMBERSHIP_OPTIONS']):
            other = locality in ('otra_urbana', 'otra_rural')
            correct_membership = membership is not None if other else (
                membership is None or (locality in MUNICIPALITIES and membership == locality))
            known = locality in MUNICIPALITIES or (other and membership in MUNICIPALITIES)
            for mask in range(8):
                state = {**_base(), 'locality': locality}
                if membership is not None:
                    state['municipality'] = membership
                state.update({field: _municipal_answers()[field] for bit, field in enumerate(municipal_fields) if mask & (1 << bit)})
                valid = correct_membership and mask == (7 if known else 0)
                add(f'municipal-matrix-{locality}-{membership}-{mask}', state, valid=valid,
                    municipal=known, membership=other)
    for municipality in MUNICIPALITIES:
        for field, catalog in [('municipalityEvaluation', 'GENERAL_EVALUATION_OPTIONS'),
                               ('municipalitySatisfaction', 'CONFORMITY_OPTIONS'),
                               ('municipalityEvolution', 'EVOLUTION_OPTIONS')]:
            for value in CATALOG[catalog]:
                add(f'municipal-scale-{municipality}-{field}-{value}',
                    {**_base(), 'locality': municipality, **_municipal_answers(), field: value}, municipal=True)
    for field in _base():
        state = _base()
        del state[field]
        add('missing-required-' + field, state, valid=False)
    for area in AREAS:
        state = _base()
        del state['areas'][area]
        add('missing-required-area-' + area, state, valid=False)
    return cases


def export_contract_fixture():
    """Return JSON-serializable examples with actual API-schema results.

    The root cross-runtime audit consumes this function over stdout; the
    standalone backend suite remains independent from frontend source files.
    """
    cases = contract_cases()
    for case in cases:
        try:
            AnswersSchema().load(case['answers'])
            case['backendValid'] = True
        except ValidationError:
            case['backendValid'] = False
    return cases


@pytest.mark.parametrize('case', contract_cases(), ids=lambda case: case['name'])
def test_complete_questionnaire_contract(case):
    if case['valid']:
        assert AnswersSchema().load(case['answers'])
    else:
        with pytest.raises(ValidationError):
            AnswersSchema().load(case['answers'])
