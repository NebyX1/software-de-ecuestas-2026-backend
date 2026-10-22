import json
import logging
import re
import smtplib
import socket
import ssl
import traceback
from pathlib import Path
from flask import current_app, g
from flask_mail import Connection, Mail, Message


class MailDeliveryError(RuntimeError):
    def __init__(self, stage, cause):
        super().__init__(f'SMTP failed during {stage}')
        self.stage = stage
        self.cause = cause


def log_mail_failure(error, *, event='admin_otp_delivery_failed', user_id=None, level=logging.ERROR):
    """Log useful diagnostics without exception text, SMTP transcripts or locals."""
    stage = error.stage if isinstance(error, MailDeliveryError) else 'message'
    cause = error.cause if isinstance(error, MailDeliveryError) else error
    reasons = (
        (ssl.SSLCertVerificationError, 'tls_certificate_invalid'),
        (ssl.SSLError, 'tls_failed'),
        (socket.gaierror, 'dns_failed'),
        (TimeoutError, 'connection_timeout'),
        (ConnectionRefusedError, 'connection_refused'),
        (smtplib.SMTPAuthenticationError, 'authentication_rejected'),
        (smtplib.SMTPRecipientsRefused, 'recipient_rejected'),
        (smtplib.SMTPSenderRefused, 'sender_rejected'),
        (smtplib.SMTPDataError, 'message_rejected'),
        (smtplib.SMTPHeloError, 'greeting_rejected'),
        (smtplib.SMTPNotSupportedError, 'smtp_feature_unsupported'),
        (smtplib.SMTPServerDisconnected, 'connection_closed'),
        (smtplib.SMTPException, 'smtp_failed'),
        (OSError, 'network_failed'),
        (AssertionError, 'message_configuration_invalid'),
    )
    reason = next((name for cls, name in reasons if isinstance(cause, cls)), 'unexpected_error')
    state = current_app.extensions['mail']
    server = str(state.server)
    if not re.fullmatch(r'[a-zA-Z0-9._:\-]{1,255}', server):
        server = '<invalid-host>'
    smtp_code = getattr(cause, 'smtp_code', None)
    response = getattr(cause, 'smtp_error', b'')
    # Recipient errors carry a mapping that must never be logged (email addresses).
    if isinstance(cause, smtplib.SMTPRecipientsRefused) and cause.recipients:
        smtp_code, response = next(iter(cause.recipients.values()))
    if isinstance(response, bytes):
        response = response.decode('ascii', errors='ignore')
    status = re.search(r'\b[245]\.\d{1,3}\.\d{1,3}\b', str(response))
    details = dict(
        event=event, stage=stage, reason=reason, error_type=type(cause).__name__,
        request_id=getattr(g, 'request_id', None), user_id=user_id,
        smtp_host=server, smtp_port=state.port, use_ssl=state.use_ssl, use_tls=state.use_tls,
        timeout_seconds=current_app.config['MAIL_TIMEOUT'],
        auth_configured=bool(state.username and state.password),
        sender_configured=bool(state.default_sender),
        smtp_code=smtp_code if isinstance(smtp_code, int) else None,
        smtp_status=status.group() if status else None,
        errno=getattr(cause, 'errno', None),
        tls_verify_code=getattr(cause, 'verify_code', None),
        # Keep the call site, but exclude source lines, exception messages and locals.
        trace=[f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
               for frame in traceback.extract_tb(cause.__traceback__)[-8:]],
    )
    current_app.logger.log(level, '%s', json.dumps(details, sort_keys=True))


class BoundedConnection(Connection):
    """Flask-Mail with verified TLS and bounded network waits."""
    def configure_host(self):
        timeout = current_app.config['MAIL_TIMEOUT']
        context = ssl.create_default_context()
        host = None
        stage = 'connect'
        try:
            if self.mail.use_ssl:
                host = smtplib.SMTP_SSL(self.mail.server, self.mail.port, timeout=timeout, context=context)
            else:
                host = smtplib.SMTP(self.mail.server, self.mail.port, timeout=timeout)
            # SMTP debug output may contain authentication material and OTPs.
            host.set_debuglevel(0)
            if self.mail.use_tls:
                stage = 'starttls'
                host.starttls(context=context)
            if self.mail.username and self.mail.password:
                stage = 'authenticate'
                host.login(self.mail.username, self.mail.password)
            return host
        except Exception as exc:
            if host is not None:
                try:
                    host.close()
                except Exception:
                    pass  # Preserve the original connection/authentication failure.
            raise MailDeliveryError(stage, exc) from exc

    def send(self, message, envelope_from=None):
        try:
            return super().send(message, envelope_from)
        except Exception as exc:
            raise MailDeliveryError('send', exc) from exc

    def __exit__(self, exc_type, exc_value, tb):
        if self.host is None:
            return
        try:
            self.host.quit()
        except Exception as exc:
            # DATA was already accepted, or a delivery error is already propagating.
            # A QUIT failure must not invalidate an accepted OTP or mask that error.
            log_mail_failure(MailDeliveryError('quit', exc), event='smtp_disconnect_failed', level=logging.WARNING)
        finally:
            try:
                self.host.close()
            except Exception as exc:
                log_mail_failure(MailDeliveryError('close', exc), event='smtp_disconnect_failed', level=logging.WARNING)


class BoundedMail(Mail):
    def connect(self):
        return BoundedConnection(current_app.extensions['mail'])


def send_2fa_email(user, code):
    from app.extensions import mail
    message = Message(
        'Código de verificación — Encuestas Lavalleja',
        recipients=[user.email],
        body=f'Tu código de acceso es {code}. Vence en diez minutos. Si no solicitaste este acceso, ignorá el correo.',
    )
    mail.send(message)
