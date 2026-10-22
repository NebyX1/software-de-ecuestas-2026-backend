import re
from uuid import UUID

from marshmallow import Schema, ValidationError, fields, pre_load, validates_schema, validate

from .catalog import AREAS, CATALOG, MUNICIPALITIES, VARIABLE_DEFINITIONS, resolved_municipality
from .device import ClientMetadataSchema


class StrictSchema(Schema):
    class Meta:
        unknown = 'raise'


def choice(name, required=True):
    return fields.String(required=required, validate=validate.OneOf(VARIABLE_DEFINITIONS[name]['options']))


class AreasSchema(StrictSchema):
    pass


AreasSchema = Schema.from_dict({key: choice('areas.' + key) for key in AREAS}, name='AreasSchema')


class AnswersSchema(StrictSchema):
    adult = fields.String(required=True, validate=validate.Equal('si'))
    lavallejaResident = fields.String(required=True, validate=validate.Equal('si'))
    locality = choice('locality')
    municipality = choice('municipality', required=False)
    gender = choice('gender')
    ageRange = choice('ageRange')
    voted2025 = choice('voted2025')
    party2025 = choice('party2025', required=False)
    generalEvaluation = choice('generalEvaluation')
    generalSatisfaction = choice('generalSatisfaction')
    managementEvolution = choice('managementEvolution')
    areas = fields.Nested(AreasSchema, required=True)
    concerns = fields.List(choice('concerns'), required=True, validate=validate.Length(min=1, max=3))
    concernOther = fields.String(validate=validate.Length(max=150))
    priorities = fields.List(choice('priorities'), required=True, validate=validate.Length(min=1, max=3))
    municipalityEvaluation = choice('municipalityEvaluation', required=False)
    municipalitySatisfaction = choice('municipalitySatisfaction', required=False)
    municipalityEvolution = choice('municipalityEvolution', required=False)
    openComment = fields.String(required=True, validate=validate.Length(min=1, max=750))

    @pre_load
    def trim_text(self, data, **kwargs):
        if isinstance(data, dict):
            data = dict(data)
            for key in ('openComment', 'concernOther'):
                if isinstance(data.get(key), str):
                    data[key] = data[key].strip()
        return data

    @validates_schema
    def conditional_answers(self, data, **kwargs):
        errors = {}
        if data['voted2025'] == 'si' and not data.get('party2025'):
            errors['party2025'] = ['Seleccioná una opción.']
        elif data['voted2025'] != 'si' and 'party2025' in data:
            errors['party2025'] = ['No corresponde a la respuesta electoral.']
        for field in ('concerns', 'priorities'):
            values = data[field]
            if len(set(values)) != len(values):
                errors[field] = ['No se permiten opciones repetidas.']
            exclusive = {'ninguno', 'ns_nc'} if field == 'concerns' else {'ns_nc'}
            if exclusive.intersection(values) and len(values) > 1:
                errors[field] = ['La opción elegida es excluyente.']
        if 'otro' in data['concerns']:
            if not data.get('concernOther'):
                errors['concernOther'] = ['Escribí qué otro problema te preocupa.']
        elif data.get('concernOther'):
            errors['concernOther'] = ['El texto requiere seleccionar Otro.']
        if data['locality'] in ('otra_urbana', 'otra_rural'):
            if not data.get('municipality'):
                errors['municipality'] = ['Seleccioná tu pertenencia a un municipio.']
        elif 'municipality' in data and (data['locality'] not in MUNICIPALITIES or data['municipality'] != data['locality']):
            errors['municipality'] = ['El municipio debe corresponder a tu localidad.']
        municipal_fields = ('municipalityEvaluation', 'municipalitySatisfaction', 'municipalityEvolution')
        known = resolved_municipality(data)
        for key in municipal_fields:
            if known and key not in data:
                errors[key] = ['Esta pregunta es obligatoria para tu municipio.']
            elif not known and key in data:
                errors[key] = ['Esta pregunta no corresponde a tu localidad.']
        if errors:
            raise ValidationError(errors)
        # Store a normalized municipality, independent from tampered client flow.
        if known:
            data['municipality'] = known


def uuid_string(value):
    try:
        if str(UUID(value)) != value.lower():
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Identificador de dispositivo inválido.')


class AttributionSchema(StrictSchema):
    utm_source = fields.String(validate=validate.Length(max=128))
    utm_medium = fields.String(validate=validate.Length(max=128))
    utm_campaign = fields.String(validate=validate.Length(max=128))
    utm_content = fields.String(validate=validate.Length(max=128))
    utm_term = fields.String(validate=validate.Length(max=128))


class LinkSchema(StrictSchema):
    deviceId = fields.String(required=True, validate=uuid_string)
    turnstileToken = fields.String(validate=validate.Length(max=2048))
    attribution = fields.Nested(AttributionSchema, load_default=dict)


class SessionSchema(StrictSchema):
    token = fields.String(required=True, validate=validate.Regexp(r'^[A-Za-z0-9_-]{43}$'))
    deviceId = fields.String(required=True, validate=uuid_string)


def normalize_phone(value):
    compact = re.sub(r'[\s.()\-]', '', value)
    if re.fullmatch(r'09[0-9]{7}', compact):
        return '+598' + compact[1:]
    if re.fullmatch(r'\+?5989[0-9]{7}', compact):
        return '+' + compact.lstrip('+')
    raise ValidationError('Ingresá un celular uruguayo válido, por ejemplo 099 123 456.')


class SubmissionSchema(SessionSchema):
    clientMetadata = fields.Nested(ClientMetadataSchema, load_default=dict)
    phone = fields.String(required=True, validate=validate.Length(max=32))
    challengeId = fields.String(required=True, validate=uuid_string)
    challengeAnswer = fields.String(required=True, validate=validate.Regexp(r'^[0-9]{1,4}$'))
    website = fields.String(load_default='', validate=validate.Length(max=200))
    answers = fields.Nested(AnswersSchema, required=True)
    consent = fields.Boolean(required=True, truthy={True}, falsy={False}, validate=validate.Equal(True))
    consentVersion = fields.String(required=True, validate=validate.OneOf(['2026-01', '2026-02']))

    @pre_load
    def literal_consent(self, data, **kwargs):
        if isinstance(data, dict) and data.get('consent') is not True:
            raise ValidationError({'consent': ['Debés aceptar participar voluntariamente.']})
        return data
