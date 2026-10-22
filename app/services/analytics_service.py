"""Portable indexed SQL filters/aggregates, no identity access."""
import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from marshmallow import ValidationError
from sqlalchemy import func, distinct, exists

from app.extensions import db
from app.models.survey import ResponseValue, SurveyResponse
from app.schemas.catalog import VARIABLE_DEFINITIONS, value_at
from app.services.device_metadata import METADATA_FILTERS, METADATA_FIELDS

LOCAL_ZONE = ZoneInfo('America/Montevideo')


def parse_filters(args):
    result = {}
    errors = {}
    for key in ('date_from', 'date_to'):
        value = args.get(key, '').strip()
        if value:
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                    raise ValueError()
                parsed = date.fromisoformat(value)
                if not 2000 <= parsed.year <= 2100:
                    raise ValueError()
                result[key] = value
            except ValueError:
                errors[key] = ['La fecha debe estar entre 2000 y 2100, en formato AAAA-MM-DD.']
    if result.get('date_from', '') > result.get('date_to', '9999-12-31'):
        errors['date_to'] = ['La fecha final debe ser posterior a la inicial.']
    for key, variable in {**VARIABLE_DEFINITIONS, **METADATA_FILTERS}.items():
        value = args.get(key, '').strip()
        if value:
            if value not in variable['options'] and not (key in METADATA_FILTERS and value == 'not_recorded'):
                errors[key] = ['Opción de filtro inválida.']
            else:
                result[key] = value
    if errors:
        raise ValidationError(errors)
    return result


def _utc_midnight(value, next_day=False):
    day = date.fromisoformat(value)
    if next_day:
        day += timedelta(days=1)
    return datetime.combine(day, time.min, tzinfo=LOCAL_ZONE).astimezone(timezone.utc).replace(tzinfo=None)


def response_query(filters):
    query = SurveyResponse.query.filter_by(survey_id=current_app.config['SURVEY_ID'])
    if filters.get('date_from'):
        query = query.filter(SurveyResponse.created_at >= _utc_midnight(filters['date_from']))
    if filters.get('date_to'):
        query = query.filter(SurveyResponse.created_at < _utc_midnight(filters['date_to'], next_day=True))
    for key, value in filters.items():
        if key in METADATA_FILTERS:
            column = getattr(SurveyResponse, key)
            query = query.filter(column.is_(None) if value == 'not_recorded' else column == value)
        if key in VARIABLE_DEFINITIONS:
            query = query.filter(exists().where(
                ResponseValue.response_id == SurveyResponse.id,
                ResponseValue.variable == key, ResponseValue.value == value,
            ))
    return query


def dashboard_data(filters):
    query = response_query(filters)
    filtered_ids = query.with_entities(SurveyResponse.id).subquery()
    total = query.count()
    grouped = db.session.query(ResponseValue.variable, ResponseValue.value, func.count()).filter(
        ResponseValue.response_id.in_(db.select(filtered_ids.c.id))
    ).group_by(ResponseValue.variable, ResponseValue.value).all()
    counts = {(key, value): count for key, value, count in grouped}
    denoms = dict(db.session.query(ResponseValue.variable, func.count(distinct(ResponseValue.response_id))).filter(
        ResponseValue.response_id.in_(db.select(filtered_ids.c.id))
    ).group_by(ResponseValue.variable).all())
    distributions = []
    for key, variable in VARIABLE_DEFINITIONS.items():
        denominator = denoms.get(key, 0)
        values = []
        for value, label in variable['options'].items():
            count = counts.get((key, value), 0)
            values.append({'value': value, 'label': label, 'count': count,
                           'percent': round(count * 100 / denominator, 1) if denominator else 0})
        distributions.append({'key': key, 'label': variable['label'], 'multiple': variable['multiple'],
                              'denominator': denominator, 'values': values})
    # Uruguay has used UTC-03 year-round since 2015. Explicit numeric offset
    # works in MariaDB without requiring its optional timezone tables.
    if db.engine.dialect.name == 'sqlite':
        day = func.date(SurveyResponse.created_at, '-3 hours')
    else:
        day = func.date(func.convert_tz(SurveyResponse.created_at, '+00:00', '-03:00'))
    timeseries = [{'date': str(day_value), 'count': count}
                  for day_value, count in query.with_entities(day, func.count()).group_by(day).order_by(day).all()]
    device_distributions = []
    for key, variable in METADATA_FILTERS.items():
        column = getattr(SurveyResponse, key)
        device_counts = dict(query.with_entities(column, func.count()).group_by(column).all())
        options = {**variable['options'], None: 'Sin registro (respuesta anterior)'}
        device_distributions.append({'key': key, 'label': variable['label'], 'denominator': total,
            'values': [{'label': label, 'count': device_counts.get(value, 0),
                        'percent': round(device_counts.get(value, 0) * 100 / total, 1) if total else 0}
                       for value, label in options.items()]})
    return {'total': total,
            'total_all': SurveyResponse.query.filter_by(survey_id=current_app.config['SURVEY_ID']).count(),
            'distributions': distributions, 'timeseries': timeseries, 'device_distributions': device_distributions}


def safe_csv_value(value):
    text = '' if value is None else str(value)
    # Whitespace/control characters before formulas also matter in Excel.
    if text.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def csv_columns():
    keys = list(VARIABLE_DEFINITIONS) + ['concernOther', 'openComment']
    return ['id', 'created_at_utc', 'consent_version'] + keys + ['technical_' + key for key in METADATA_FIELDS]


def csv_record(response):
    keys = list(VARIABLE_DEFINITIONS) + ['concernOther', 'openComment']
    row = [response.id, response.created_at.isoformat() + 'Z', response.consent_version]
    for key in keys:
        value = value_at(response.answers, key)
        row.append('|'.join(value) if isinstance(value, list) else value)
    row.extend((response.device_metadata or {}).get(key) for key in METADATA_FIELDS)
    return [safe_csv_value(value) for value in row]


def iter_csv(filters):
    """Stream opinions and descriptive metadata, never phones or identifiers."""
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\r\n')
    writer.writerow(csv_columns())
    yield '\ufeff' + buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    # yield_per keeps memory bounded instead of loading every answer.
    for response in response_query(filters).order_by(SurveyResponse.created_at, SurveyResponse.id).yield_per(250):
        writer.writerow(csv_record(response))
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
