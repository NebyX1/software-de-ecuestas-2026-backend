"""Bounded, optional browser reports. These values are not identity proofs."""
from marshmallow import Schema, fields, validate, ValidationError, pre_load


class StrictSchema(Schema):
    class Meta:
        unknown = 'raise'


class DimensionsSchema(StrictSchema):
    width = fields.Integer(required=True, strict=True, validate=validate.Range(min=1, max=32768))
    height = fields.Integer(required=True, strict=True, validate=validate.Range(min=1, max=32768))

    @pre_load
    def integers_only(self, data, **kwargs):
        if isinstance(data, dict) and any(type(data.get(key)) is not int for key in ('width', 'height')):
            raise ValidationError('Las dimensiones deben ser enteros.')
        return data


class BrandSchema(StrictSchema):
    brand = fields.String(required=True, validate=validate.Length(min=1, max=64))
    version = fields.String(required=True, validate=validate.Regexp(r'^[0-9.]{1,32}$'))


class ClientHintsSchema(StrictSchema):
    platform = fields.String(validate=validate.Length(max=64))
    platformVersion = fields.String(validate=validate.Regexp(r'^[0-9.]{0,32}$'))
    model = fields.String(validate=validate.Length(max=128))
    mobile = fields.Boolean()
    brands = fields.List(fields.Nested(BrandSchema), validate=validate.Length(max=8))
    fullVersionList = fields.List(fields.Nested(BrandSchema), validate=validate.Length(max=8))

    @pre_load
    def boolean_only(self, data, **kwargs):
        if isinstance(data, dict) and 'mobile' in data and type(data['mobile']) is not bool:
            raise ValidationError({'mobile': ['Se esperaba un booleano.']})
        return data


class ClientMetadataSchema(StrictSchema):
    language = fields.String(validate=validate.Regexp(r'^[A-Za-z0-9-]{1,64}$'))
    timezone = fields.String(validate=validate.Length(min=1, max=64))
    screen = fields.Nested(DimensionsSchema)
    viewport = fields.Nested(DimensionsSchema)
    pixelRatio = fields.Float(validate=validate.Range(min=0.1, max=16), allow_nan=False)
    touchPoints = fields.Integer(strict=True, validate=validate.Range(min=0, max=100))
    clientHints = fields.Nested(ClientHintsSchema)

    @pre_load
    def numbers_only(self, data, **kwargs):
        if isinstance(data, dict):
            if 'touchPoints' in data and type(data['touchPoints']) is not int:
                raise ValidationError({'touchPoints': ['Se esperaba un entero.']})
            if 'pixelRatio' in data and type(data['pixelRatio']) not in (int, float):
                raise ValidationError({'pixelRatio': ['Se esperaba un número.']})
        return data
