"""Exact answer codes/labels copied from the original questionnaire."""
import json
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name('catalog_data.json').read_text(encoding='utf-8'))
AREAS = {**CATALOG['AREAS_A'], **CATALOG['AREAS_B']}
MUNICIPALITIES = CATALOG['MUNICIPALITIES']
VARIABLE_DEFINITIONS = {}


def _variable(key, label, options, multiple=False):
    VARIABLE_DEFINITIONS[key] = {'label': label, 'options': options, 'multiple': multiple}


_variable('adult', 'Mayor de edad', {'si': 'Sí', 'no': 'No'})
_variable('lavallejaResident', 'Residente en Lavalleja', {'si': 'Sí', 'no': 'No'})
_variable('locality', 'Localidad', CATALOG['LOCALITIES'])
_variable('municipality', 'Municipio', CATALOG['MUNICIPALITY_MEMBERSHIP_OPTIONS'])
_variable('gender', 'Género', CATALOG['GENDER_OPTIONS'])
_variable('ageRange', 'Rango de edad', CATALOG['AGE_RANGE_OPTIONS'])
_variable('voted2025', 'Votó en las elecciones departamentales de 2025', CATALOG['VOTED_2025_OPTIONS'])
_variable('party2025', 'Partido votado en 2025', CATALOG['PARTY_2025_OPTIONS'])
_variable('generalEvaluation', 'Evaluación de la gestión departamental', CATALOG['GENERAL_EVALUATION_OPTIONS'])
_variable('generalSatisfaction', 'Conformidad con la gestión', CATALOG['CONFORMITY_OPTIONS'])
_variable('managementEvolution', 'Evolución de la gestión', CATALOG['EVOLUTION_OPTIONS'])
for key, label in AREAS.items():
    _variable('areas.' + key, label, CATALOG['GENERAL_EVALUATION_OPTIONS'])
_variable('concerns', 'Principales preocupaciones', CATALOG['CONCERN_OPTIONS'], multiple=True)
_variable('priorities', 'Prioridades', CATALOG['PRIORITY_OPTIONS'], multiple=True)
_variable('municipalityEvaluation', 'Evaluación del municipio', CATALOG['GENERAL_EVALUATION_OPTIONS'])
_variable('municipalitySatisfaction', 'Conformidad con el municipio', CATALOG['CONFORMITY_OPTIONS'])
_variable('municipalityEvolution', 'Evolución del municipio', CATALOG['EVOLUTION_OPTIONS'])


def value_at(answers, key):
    if key.startswith('areas.'):
        return answers.get('areas', {}).get(key.split('.', 1)[1])
    return answers.get(key)


def resolved_municipality(answers):
    locality = answers.get('locality')
    if locality in MUNICIPALITIES:
        return locality
    if locality in ('otra_urbana', 'otra_rural') and answers.get('municipality') in MUNICIPALITIES:
        return answers['municipality']
    return None
