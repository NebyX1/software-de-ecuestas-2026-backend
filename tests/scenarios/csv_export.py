"""Run the same public/API/CSV scenario with either MariaDB connector."""
import csv
import io
import re
from uuid import uuid4

from app.extensions import db, mail
from app.models.survey import SurveyResponse, ParticipantIdentity, ResponseValue, SurveyInvitation
from app.models.user import User, TwoFactorCode
from app.models.audit import ActivityLog
from app.schemas.catalog import AREAS
from app.services.analytics_service import dashboard_data


def verify_large_csv(app):
    assert app.testing and app.config['SURVEY_ID'].startswith('integration-')
    survey = app.config['SURVEY_ID']
    username = 'csv-' + uuid4().hex[:20]
    user_id = None
    expected = {}
    try:
        for index in range(261):
            client = app.test_client()
            device = str(uuid4())
            issued = client.post('/api/survey/links', json={'deviceId': device})
            assert issued.status_code == 201, issued.json
            binding = {'deviceId': device, 'token': issued.json['token']}
            challenge = client.post('/api/survey/challenge', json=binding)
            assert challenge.status_code == 200, challenge.json
            comment = f'Caso {index}, "niñez y salud"\nSegunda línea: caminería 🧉.'
            concerns = ['costo_vida', 'seguridad'] if index % 2 else ['ns_nc']
            opinion = {
                'adult': 'si', 'lavallejaResident': 'si', 'locality': 'minas', 'gender': 'ns_nc', 'ageRange': '35_44', 'voted2025': 'pnr',
                'generalEvaluation': 'buena', 'generalSatisfaction': 'conforme', 'managementEvolution': 'aprox_igual',
                'areas': {key: 'ns_nc' for key in AREAS}, 'concerns': concerns, 'priorities': ['ns_nc'], 'openComment': comment,
            }
            result = client.post('/api/survey/responses', json={
                **binding, 'answers': opinion, 'phone': f'098{index:06d}', 'consent': True, 'consentVersion': '2026-02',
                'challengeId': challenge.json['challengeId'], 'challengeAnswer': str(sum(map(int, re.findall(r'\d+', challenge.json['question'])))), 'website': '',
            })
            assert result.status_code == 201, result.json
            expected[comment] = '|'.join(concerns)
        with app.app_context():
            user = User(username=username, email=username + '@example.org', is_active=True, is_superuser=False)
            user.set_password('correct-password-2026!')
            db.session.add(user); db.session.commit()
            user_id = user.id
        admin = app.test_client()
        assert admin.get('/admin/responses/export.csv').status_code == 302
        assert admin.get('/admin/login').status_code == 200
        with admin.session_transaction() as session:
            verifier = session['captcha_result']
        with app.app_context(), mail.record_messages() as messages:
            login = admin.post('/admin/login', data={'email': username + '@example.org', 'password': 'correct-password-2026!', 'captcha': str(verifier)})
            assert login.status_code == 302 and login.location.endswith('/admin/2fa')
            assert len(messages) == 1
            code = re.search(r'\b\d{6}\b', messages[0].body).group()
        assert admin.post('/admin/2fa', data={'code': code}).status_code == 302
        result = admin.get('/admin/responses/export.csv')
        assert result.status_code == 200 and result.mimetype == 'text/csv'
        assert result.headers['Content-Disposition'].startswith('attachment;')
        assert result.data.startswith(b'\xef\xbb\xbf')
        reader = csv.DictReader(io.StringIO(result.data.decode('utf-8-sig'), newline=''))
        rows = list(reader)
        assert len(rows) == 261 and len({row['id'] for row in rows}) == 261
        assert len(reader.fieldnames) == len(set(reader.fieldnames)) == 57
        assert {row['openComment']: row['concerns'] for row in rows} == expected
        assert all(row['municipalityEvaluation'] == '' and row['municipality'] == '' for row in rows)
        assert not {'phone', 'deviceId', 'device_hash', 'ip_hash', 'token'} & set(reader.fieldnames)
        with app.app_context():
            charts = dashboard_data({})
            assert charts['total'] == 261
            concerns = next(chart for chart in charts['distributions'] if chart['key'] == 'concerns')
            assert concerns['denominator'] == 261
            assert sum(value['count'] for value in concerns['values']) == 391
            assert ActivityLog.query.filter_by(user_id=user_id, action='EXPORT_RESPONSES_CSV').count() == 1
            driver = db.engine.dialect.driver
        assert admin.get('/admin/responses?page=11').status_code == 200
        assert admin.post('/admin/logout').status_code == 302
        assert admin.get('/admin/responses/export.csv').status_code == 302
        return {'submitted': 261, 'csvRows': len(rows), 'columns': len(reader.fieldnames), 'driver': driver, 'unicodeAndMultiline': True, 'uniqueIds': True}
    finally:
        with app.app_context():
            db.session.rollback()
            if user_id is not None:
                db.session.execute(db.delete(ActivityLog).where(ActivityLog.user_id == user_id))
                db.session.execute(db.delete(TwoFactorCode).where(TwoFactorCode.user_id == user_id))
                db.session.execute(db.delete(User).where(User.id == user_id))
            ids = db.select(SurveyResponse.id).where(SurveyResponse.survey_id == survey)
            db.session.execute(db.delete(ResponseValue).where(ResponseValue.response_id.in_(ids)))
            for model in (SurveyResponse, SurveyInvitation, ParticipantIdentity):
                db.session.execute(db.delete(model).where(model.survey_id == survey))
            db.session.commit()
