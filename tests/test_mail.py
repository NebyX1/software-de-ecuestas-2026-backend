import json
import logging
import smtplib
import socket
import ssl

import pytest
from flask import Flask, g
from flask_mail import Message

from app.commands import check_mail
from app.config import build_config, validate_config
from app.extensions import mail
from app.services.mail_service import MailDeliveryError, log_mail_failure


@pytest.fixture
def smtp_app():
    app = Flask('mail-tests')
    app.config.update(
        MAIL_SERVER='smtp.example.org', MAIL_PORT=465,
        MAIL_USE_SSL=True, MAIL_USE_TLS=False, MAIL_TIMEOUT=10,
        MAIL_USERNAME='mailer@example.org', MAIL_PASSWORD='private-smtp-password',
        MAIL_DEFAULT_SENDER='mailer@example.org', MAIL_SUPPRESS_SEND=False, MAIL_DEBUG=False,
    )
    mail.init_app(app)
    app.cli.add_command(check_mail)
    return app


@pytest.fixture
def smtp(monkeypatch):
    class SMTP:
        def __init__(self):
            self.messages = []
            self.closed = False

        def set_debuglevel(self, level):
            assert level == 0

        def login(self, username, password):
            pass

        def sendmail(self, sender, recipients, body, *options):
            self.messages.append(body)
            return {}

        def quit(self):
            return 221, b'Bye'

        def close(self):
            self.closed = True

    server = SMTP()
    monkeypatch.setattr('app.services.mail_service.smtplib.SMTP_SSL', lambda *args, **kwargs: server)
    return server


def events(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.getMessage().startswith('{"auth_configured"')]


def test_authentication_failure_closes_socket_and_redacts_server_response(smtp_app, smtp, monkeypatch, caplog):
    def reject(*args):
        raise smtplib.SMTPAuthenticationError(535, b'5.7.8 private-smtp-password mailer@example.org OTP 654321')
    monkeypatch.setattr(smtp, 'login', reject)
    with smtp_app.app_context():
        g.request_id = 'request-test'
        with pytest.raises(MailDeliveryError) as caught:
            mail.send(Message('OTP', recipients=['admin@example.org'], body='654321'))
        log_mail_failure(caught.value, user_id=42)
    assert smtp.closed
    assert not smtp.messages
    entry = events(caplog)[-1]
    assert entry['stage'] == 'authenticate'
    assert entry['reason'] == 'authentication_rejected'
    assert entry['smtp_code'] == 535 and entry['smtp_status'] == '5.7.8'
    assert entry['request_id'] == 'request-test' and entry['user_id'] == 42
    assert entry['trace']
    for private in ('private-smtp-password', 'mailer@example.org', 'admin@example.org', '654321'):
        assert private not in caplog.text


def test_accepted_message_survives_quit_failure(smtp_app, smtp, monkeypatch, caplog):
    def disconnect():
        raise smtplib.SMTPServerDisconnected('server closed before QUIT reply')
    monkeypatch.setattr(smtp, 'quit', disconnect)
    with smtp_app.app_context():
        mail.send(Message('OTP', recipients=['admin@example.org'], body='654321'))
    assert len(smtp.messages) == 1 and smtp.closed
    entry = events(caplog)[-1]
    assert entry['event'] == 'smtp_disconnect_failed' and entry['stage'] == 'quit'
    assert caplog.records[-1].levelno == logging.WARNING
    assert '654321' not in caplog.text


def test_quit_failure_does_not_mask_rejection_during_data(smtp_app, smtp, monkeypatch, caplog):
    def reject(*args):
        raise smtplib.SMTPDataError(554, b'5.7.1 message content 654321')
    def disconnect():
        raise smtplib.SMTPServerDisconnected('QUIT failed')
    monkeypatch.setattr(smtp, 'sendmail', reject)
    monkeypatch.setattr(smtp, 'quit', disconnect)
    with smtp_app.app_context():
        with pytest.raises(MailDeliveryError) as caught:
            mail.send(Message('OTP', recipients=['admin@example.org'], body='654321'))
        log_mail_failure(caught.value)
    assert smtp.closed
    entry = events(caplog)[-1]
    assert entry['stage'] == 'send' and entry['reason'] == 'message_rejected'
    assert entry['smtp_code'] == 554 and entry['smtp_status'] == '5.7.1'
    assert '654321' not in caplog.text


@pytest.mark.parametrize(('error', 'reason', 'code'), [
    (socket.gaierror(-2, 'sensitive text'), 'dns_failed', None),
    (TimeoutError('sensitive text'), 'connection_timeout', None),
    (ssl.SSLCertVerificationError(1, 'sensitive text'), 'tls_certificate_invalid', None),
    (ConnectionRefusedError(10061, 'sensitive text'), 'connection_refused', None),
    (smtplib.SMTPRecipientsRefused({'admin@example.org': (550, b'5.1.1 sensitive text')}), 'recipient_rejected', 550),
])
def test_diagnostics_distinguish_network_tls_and_recipient_errors(smtp_app, caplog, error, reason, code):
    with smtp_app.app_context():
        log_mail_failure(MailDeliveryError('connect', error))
    entry = events(caplog)[-1]
    assert entry['reason'] == reason and entry['smtp_code'] == code
    assert entry['smtp_host'] == 'smtp.example.org' and entry['smtp_port'] == 465
    assert entry['use_ssl'] is True and entry['use_tls'] is False
    assert 'sensitive text' not in caplog.text and 'admin@example.org' not in caplog.text


def test_check_mail_authenticates_without_sending(smtp_app, smtp):
    result = smtp_app.test_cli_runner().invoke(args=['check-mail'])
    assert result.exit_code == 0
    assert 'Autenticación: verificada' in result.output
    assert 'No se envió ningún mensaje' in result.output
    assert not smtp.messages and smtp.closed


def test_check_mail_returns_failure_and_safe_diagnostics(smtp_app, smtp, monkeypatch, caplog):
    def reject(*args):
        raise smtplib.SMTPAuthenticationError(535, b'5.7.8 private-smtp-password')
    monkeypatch.setattr(smtp, 'login', reject)
    result = smtp_app.test_cli_runner().invoke(args=['check-mail'])
    assert result.exit_code == 1
    assert events(caplog)[-1]['event'] == 'smtp_check_failed'
    assert 'private-smtp-password' not in result.output + caplog.text
    assert not smtp.messages and smtp.closed


def test_check_mail_cannot_claim_success_when_suppressed(smtp_app, smtp):
    smtp_app.extensions['mail'].suppress = True
    result = smtp_app.test_cli_runner().invoke(args=['check-mail'])
    assert result.exit_code == 1 and 'no se comprobó SMTP' in result.output
    assert not smtp.messages and not smtp.closed


@pytest.mark.parametrize('overrides', [
    {'MAIL_USERNAME': 'only-user@example.org', 'MAIL_PASSWORD': None},
    {'MAIL_USERNAME': None, 'MAIL_PASSWORD': 'only-password'},
    {'MAIL_TIMEOUT': 0},
    {'MAIL_PORT': 465, 'MAIL_USE_SSL': False},
])
def test_invalid_smtp_config_fails_at_startup(overrides):
    app = Flask('invalid-smtp')
    app.config.update(build_config('testing'))
    app.config.update(overrides)
    with pytest.raises(ValueError, match='MAIL_'):
        validate_config(app)


def test_mail_booleans_accept_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv('MAIL_USE_SSL', ' true \n')
    monkeypatch.setenv('MAIL_USE_TLS', ' false \n')
    monkeypatch.setenv('MAIL_TIMEOUT', '20')
    config = build_config('testing')
    assert config['MAIL_USE_SSL'] is True and config['MAIL_USE_TLS'] is False
    assert config['MAIL_TIMEOUT'] == 20
