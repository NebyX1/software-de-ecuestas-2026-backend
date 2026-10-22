import secrets
import click
from email_validator import validate_email, EmailNotValidError
from flask.cli import with_appcontext
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.user import User


@click.command('create-admin')
@click.argument('username')
@click.argument('email')
@click.argument('password', required=False)
@click.argument('is_superuser', default='false', type=click.Choice(['true', 'false'], case_sensitive=False))
@click.option('--superuser', 'force_superuser', is_flag=True, help='Crear superadmin con contraseña solicitada de forma oculta.')
@with_appcontext
def create_admin(username, email, password, is_superuser, force_superuser):
    """Compatible: create-admin USERNAME EMAIL PASSWORD true|false."""
    if not 3 <= len(username.strip()) <= 64:
        raise click.ClickException('El nombre debe tener de 3 a 64 caracteres.')
    try:
        email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise click.ClickException('Correo electrónico inválido.') from exc
    if password is None:
        password = click.prompt('Contraseña', hide_input=True, confirmation_prompt=True)
    if not 12 <= len(password) <= 128:
        raise click.ClickException('La contraseña debe tener entre 12 y 128 caracteres.')
    if db.session.scalar(db.select(User.id).where(or_(User.email == email, User.username == username.strip()))):
        raise click.ClickException('El correo o nombre de usuario ya existe.')
    user = User(username=username.strip(), email=email, is_active=True, is_superuser=force_superuser or is_superuser.lower() == 'true')
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise click.ClickException('El correo o nombre de usuario ya existe.') from exc
    click.echo(f'{"Super Admin" if user.is_superuser else "Admin"} {user.username} creado correctamente.')


@click.command('rotate-secret')
def rotate_secret():
    """Genera un secreto; no modifica la configuración."""
    click.echo(secrets.token_urlsafe(48))


@click.command('check-mail')
@with_appcontext
def check_mail():
    """Comprueba conexión, TLS y autenticación SMTP sin enviar mensajes."""
    from flask import current_app
    from app.extensions import mail
    from app.services.mail_service import log_mail_failure
    state = current_app.extensions['mail']
    if state.suppress:
        raise click.ClickException('El envío está suprimido en este entorno; no se comprobó SMTP.')
    try:
        with mail.connect():
            pass
    except Exception as exc:
        log_mail_failure(exc, event='smtp_check_failed')
        raise click.ClickException('Falló la comprobación SMTP. Revisá el diagnóstico smtp_check_failed en los logs.') from None
    auth = 'verificada' if state.username and state.password else 'no configurada (relay sin autenticación)'
    security = 'SSL/TLS' if state.use_ssl else 'STARTTLS' if state.use_tls else 'sin TLS'
    click.echo(f'Conexión SMTP correcta. Seguridad: {security}. Autenticación: {auth}. No se envió ningún mensaje.')


@click.command('seed-data')
@with_appcontext
def seed_data():
    click.echo('El catálogo de preguntas está versionado en código; no requiere datos demo.')


@click.command('cleanup-survey')
@with_appcontext
def cleanup_survey():
    """Descarta invitaciones expiradas; Redis vence los desafíos transitorios."""
    from app.services.survey_service import purge_invitation_metadata
    result = purge_invitation_metadata()
    click.echo(f"Invitaciones eliminadas: {result['invitations_deleted']}.")
