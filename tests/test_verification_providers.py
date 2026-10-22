from unittest.mock import Mock

import pytest
import requests

from app import create_app
from app.extensions import db
from app.models.survey import SurveyInvitation
from app.services.antibot_service import verify_turnstile
from app.services.survey_errors import SurveyError


@pytest.fixture
def app():
    instance = create_app('testing', {
        'TURNSTILE_REQUIRED': True, 'TURNSTILE_SECRET_KEY': 'test-server-secret',
        'TURNSTILE_HOSTNAME': 'encuesta.example.uy',
    })
    with instance.app_context():
        db.create_all()
        yield instance
        db.session.remove()
        db.drop_all()


def response(payload, status=200):
    result = Mock(status_code=status)
    result.json.return_value = payload
    return result


@pytest.mark.parametrize('payload', [
    {'success': False},
    {'success': True, 'hostname': 'attacker.example', 'action': 'survey_start'},
    {'success': True, 'hostname': 'encuesta.example.uy', 'action': 'different_action'},
    {'success': 'true', 'hostname': 'encuesta.example.uy', 'action': 'survey_start'},
])
def test_turnstile_checks_success_hostname_and_action(app, monkeypatch, payload):
    monkeypatch.setattr('app.services.antibot_service.requests.post', Mock(return_value=response(payload)))
    with pytest.raises(SurveyError) as exc:
        verify_turnstile('a-real-browser-token')
    assert exc.value.code == 'captcha_invalid'
    assert SurveyInvitation.query.count() == 0


def test_turnstile_accepts_verified_server_result(app, monkeypatch):
    post = Mock(return_value=response({'success': True, 'hostname': 'encuesta.example.uy', 'action': 'survey_start'}))
    monkeypatch.setattr('app.services.antibot_service.requests.post', post)
    verify_turnstile('browser-token')
    call = post.call_args
    assert call.args[0] == 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
    assert call.kwargs['data']['secret'] == 'test-server-secret'
    assert call.kwargs['data']['response'] == 'browser-token'
    assert call.kwargs['timeout'] == (3, 8)


@pytest.mark.parametrize('failure', [requests.Timeout(), ValueError()])
def test_turnstile_provider_failure_fails_closed(app, monkeypatch, failure):
    post = Mock(side_effect=failure)
    monkeypatch.setattr('app.services.antibot_service.requests.post', post)
    with pytest.raises(SurveyError) as exc:
        verify_turnstile('browser-token')
    assert exc.value.status == 503


def test_turnstile_malformed_success_body_fails_closed(app, monkeypatch):
    monkeypatch.setattr('app.services.antibot_service.requests.post', Mock(return_value=response([])))
    with pytest.raises(SurveyError) as exc:
        verify_turnstile('browser-token')
    assert exc.value.status == 503
