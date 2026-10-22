import smtplib
import ssl
from flask import current_app
from flask_mail import Connection, Mail, Message


class BoundedConnection(Connection):
    """Flask-Mail with verified TLS and bounded network waits."""
    def configure_host(self):
        timeout = current_app.config['MAIL_TIMEOUT']
        context = ssl.create_default_context()
        if self.mail.use_ssl:
            host = smtplib.SMTP_SSL(self.mail.server, self.mail.port, timeout=timeout, context=context)
        else:
            host = smtplib.SMTP(self.mail.server, self.mail.port, timeout=timeout)
        # SMTP debug output may contain authentication material and OTPs.
        host.set_debuglevel(0)
        if self.mail.use_tls:
            host.starttls(context=context)
        if self.mail.username and self.mail.password:
            host.login(self.mail.username, self.mail.password)
        return host


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
