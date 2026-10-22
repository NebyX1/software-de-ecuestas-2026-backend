from datetime import datetime, timedelta
import csv
import io
import re
import secrets
import time
from flask import render_template, redirect, url_for, flash, request, session, abort, Response, current_app, stream_with_context
from flask_login import login_user, login_required, logout_user, current_user, fresh_login_required
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from app.extensions import db, limiter
from app.models.user import User, TwoFactorCode
from app.models.audit import ActivityLog
from app.forms.auth import LoginForm, TwoFactorForm
from app.forms.admin import AdminUserCreateForm, AdminUserUpdateForm
from app.utils.security import log_activity, digest, csv_safe
from app.utils.time import utcnow
from app.services.mail_service import send_2fa_email
from app.services.admin_session_service import create_auth_session, revoke_auth_session
from app.services.device_metadata import METADATA_FILTERS, metadata_display_values
from . import admin_bp


def require_superuser():
    if not current_user.is_superuser:
        log_activity('UNAUTHORIZED_ACCESS', 'Gestión de administradores o auditoría sin privilegios.')
        db.session.commit()
        abort(403)


def new_verifier():
    first, second = secrets.randbelow(10) + 1, secrets.randbelow(10) + 1
    session['captcha_result'] = first + second
    session['captcha_created_at'] = time.time()
    return f'¿Cuánto es {first} + {second}?'


def login_key():
    # Shared Redis counter per account, independent of rotating source IPs.
    return 'account:' + digest(request.form.get('email', '').strip().lower()[:255])


@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
@limiter.limit('10 per hour', key_func=login_key, methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    form = LoginForm()
    status = 200
    if request.method == 'POST':
        expected = session.pop('captcha_result', None)
        issued = session.pop('captcha_created_at', 0)
        verified = expected is not None and str(expected) == form.captcha.data and 0 <= time.time() - issued < 600
        if form.validate_on_submit() and verified:
            user = db.session.scalar(db.select(User).where(User.email == form.email.data.strip().lower()))
            if user and user.is_active and user.check_password(form.password.data):
                code = ''.join(secrets.choice('0123456789') for _ in range(6))
                challenge = secrets.token_urlsafe(32)
                now = utcnow()
                db.session.execute(update(TwoFactorCode).where(TwoFactorCode.user_id == user.id, TwoFactorCode.consumed_at.is_(None)).values(consumed_at=now))
                tf_code = TwoFactorCode(user.id, code, digest(challenge), user.auth_version, current_app.config['ADMIN_OTP_TTL_SECONDS'])
                db.session.add(tf_code)
                db.session.commit()
                try:
                    send_2fa_email(user, code)
                except Exception:
                    tf_code.consumed_at = utcnow()
                    db.session.commit()
                    current_app.logger.error('Admin OTP delivery failed user_id=%s', user.id)
                    flash('No pudimos enviar el código de verificación. Intentá más tarde.', 'error')
                    status = 503
                else:
                    session.clear()
                    session['2fa_challenge'] = challenge
                    session['2fa_user_id'] = user.id
                    return redirect(url_for('admin.verify_2fa'))
            else:
                # Perform comparable Argon2 work for unknown accounts.
                if not user:
                    from app.models.user import ph
                    ph.hash(form.password.data or '')
                flash('Correo, contraseña o número verificador inválidos.', 'error')
                status = 400
        else:
            flash('Correo, contraseña o número verificador inválidos.', 'error')
            status = 400
    return render_template('admin/login.html', form=form, captcha_question=new_verifier()), status


@admin_bp.route('/2fa', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def verify_2fa():
    challenge = session.get('2fa_challenge')
    user_id = session.get('2fa_user_id')
    if not challenge or not user_id:
        return redirect(url_for('admin.login'))
    form = TwoFactorForm()
    if request.method == 'POST':
        now = utcnow()
        # Lock the challenge across workers before counting attempts/consuming it.
        tf_code = db.session.scalar(db.select(TwoFactorCode).where(TwoFactorCode.challenge_hash == digest(challenge), TwoFactorCode.user_id == user_id).with_for_update())
        user = db.session.get(User, user_id)
        valid_challenge = tf_code and user and user.is_active and tf_code.auth_version == user.auth_version and tf_code.consumed_at is None and tf_code.expires_at > now and tf_code.attempts < current_app.config['ADMIN_OTP_MAX_ATTEMPTS']
        if not valid_challenge:
            db.session.rollback()
            session.clear()
            flash('El código venció o alcanzó el máximo de intentos. Iniciá sesión nuevamente.', 'error')
            return redirect(url_for('admin.login'))
        tf_code.attempts += 1
        if form.validate_on_submit() and tf_code.verify_code(form.code.data):
            tf_code.consumed_at = now
            user.last_login_at = now
            log_activity('LOGIN', 'Inicio de sesión con contraseña, verificador y código por correo.', user)
            db.session.commit()
            version = user.auth_version
            session.clear()
            create_auth_session(user)
            login_user(user, remember=False, fresh=True)
            session['auth_version'] = version
            session.permanent = True
            return redirect(url_for('admin.dashboard'))
        if tf_code.attempts >= current_app.config['ADMIN_OTP_MAX_ATTEMPTS']:
            tf_code.consumed_at = now
            session.clear()
        db.session.commit()
        flash('Código inválido o expirado.', 'error')
        return render_template('admin/verify_2fa.html', form=form), 400
    return render_template('admin/verify_2fa.html', form=form)


@admin_bp.post('/logout')
@login_required
def logout():
    revoke_auth_session()
    log_activity('LOGOUT', 'Cierre de sesión manual.')
    db.session.commit()
    logout_user()
    session.clear()
    return redirect(url_for('admin.login'))


def survey_filters():
    from app.services.analytics_service import parse_filters
    return parse_filters(request.args)


@admin_bp.get('/')
@login_required
def index():
    return redirect(url_for('admin.dashboard'))


@admin_bp.get('/dashboard')
@login_required
def dashboard():
    from app.services.analytics_service import dashboard_data
    from app.schemas.catalog import VARIABLE_DEFINITIONS
    filters = survey_filters()
    data = dashboard_data(filters)
    return render_template('admin/dashboard.html', data=data, filters=filters, variables=VARIABLE_DEFINITIONS, metadata_filters=METADATA_FILTERS)


@admin_bp.get('/simulation')
@login_required
def simulation():
    from app.services.simulation_service import simulation_generation
    return render_template('admin/simulation.html', enabled=bool(simulation_generation()),
                           simulation_url=current_app.config['FRONTEND_URL'] + '/simular')


@admin_bp.post('/simulation/enable')
@fresh_login_required
@limiter.limit('30 per hour')
def simulation_enable():
    from app.services.simulation_service import enable_simulation
    enable_simulation()
    flash('Simulación habilitada.', 'success')
    return redirect(url_for('admin.simulation'))


@admin_bp.post('/simulation/restart')
@fresh_login_required
@limiter.limit('30 per hour')
def simulation_restart():
    from app.services.simulation_service import enable_simulation
    enable_simulation(restart=True)
    flash('Simulación reiniciada. Los accesos de prueba anteriores fueron invalidados.', 'success')
    return redirect(url_for('admin.simulation'))


@admin_bp.post('/simulation/disable')
@fresh_login_required
@limiter.limit('30 per hour')
def simulation_disable():
    from app.services.simulation_service import disable_simulation
    disable_simulation()
    flash('Simulación deshabilitada. Los accesos de prueba fueron cerrados.', 'success')
    return redirect(url_for('admin.simulation'))


@admin_bp.get('/responses')
@login_required
def responses_list():
    from app.services.analytics_service import response_query
    from app.schemas.catalog import VARIABLE_DEFINITIONS
    from app.models.survey import SurveyResponse
    filters = survey_filters()
    query = response_query(filters).order_by(SurveyResponse.created_at.desc(), SurveyResponse.id.desc())
    page = max(1, request.args.get('page', 1, type=int))
    pagination = query.paginate(page=page, per_page=25, error_out=False, max_per_page=25)
    return render_template('admin/responses.html', pagination=pagination, filters=filters, variables=VARIABLE_DEFINITIONS, metadata_filters=METADATA_FILTERS)


@admin_bp.get('/responses/<string:id>')
@login_required
def response_detail(id):
    from app.models.survey import SurveyResponse
    from app.schemas.catalog import VARIABLE_DEFINITIONS
    response = db.get_or_404(SurveyResponse, id)
    if response.survey_id != current_app.config['SURVEY_ID']:
        abort(404)
    return render_template('admin/response_detail.html', response=response, variables=VARIABLE_DEFINITIONS, device_values=metadata_display_values(response))


@admin_bp.get('/responses/export.csv')
@fresh_login_required
@limiter.limit('10 per hour')
def responses_export_csv():
    from app.services.analytics_service import iter_csv
    filters = survey_filters()
    log_activity('EXPORT_RESPONSES_CSV', 'Exportación de respuestas y datos técnicos con filtros; sin teléfonos ni identificadores de dispositivo.')
    db.session.commit()
    return Response(stream_with_context(iter_csv(filters)), content_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="respuestas_{utcnow():%Y%m%d_%H%M%S}.csv"', 'X-Content-Type-Options': 'nosniff'})


def duplicate_user(username, email, except_id=None):
    query = db.select(User).where(or_(User.username == username, User.email == email))
    if except_id is not None:
        query = query.where(User.id != except_id)
    return db.session.scalar(query)


def locked_superusers():
    # All mutations lock the same ordered set, protecting the last active superadmin.
    return db.session.scalars(db.select(User).where(User.is_superuser.is_(True), User.is_active.is_(True)).order_by(User.id).with_for_update().execution_options(populate_existing=True)).all()


@admin_bp.route('/users', methods=['GET', 'POST'])
@fresh_login_required
def users_list():
    require_superuser()
    form = AdminUserCreateForm()
    status = 200
    if request.method == 'POST':
        if form.validate_on_submit():
            username, email = form.username.data.strip(), form.email.data.strip().lower()
            if duplicate_user(username, email):
                flash('El correo o nombre de usuario ya existe.', 'error')
                status = 400
            else:
                user = User(username=username, email=email, is_superuser=form.is_superuser.data, is_active=True)
                user.set_password(form.password.data)
                db.session.add(user)
                log_activity('CREATE_ADMIN', f'Creación de usuario {username}; superadmin={user.is_superuser}.')
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    flash('El correo o nombre de usuario ya existe.', 'error')
                    status = 400
                else:
                    flash('Administrador creado.', 'success')
                    return redirect(url_for('admin.users_list'))
        else:
            status = 400
    users = db.session.scalars(db.select(User).order_by(User.created_at.desc())).all()
    return render_template('admin/users.html', users=users, form=form), status


@admin_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@fresh_login_required
def user_edit(id):
    require_superuser()
    supers = locked_superusers() if request.method == 'POST' else []
    user = db.session.scalar(db.select(User).where(User.id == id).with_for_update().execution_options(populate_existing=True)) if request.method == 'POST' else db.session.get(User, id)
    if user is None:
        abort(404)
    form = AdminUserUpdateForm(obj=user)
    status = 200
    if request.method == 'POST':
        if form.validate_on_submit():
            username, email = form.username.data.strip(), form.email.data.strip().lower()
            if user.is_superuser and user.is_active and (not form.is_active.data or not form.is_superuser.data) and len(supers) <= 1:
                flash('Debe existir al menos un super administrador activo.', 'error')
                status = 400
            elif duplicate_user(username, email, user.id):
                flash('El correo o nombre de usuario ya existe.', 'error')
                status = 400
            else:
                user.username, user.email = username, email
                user.is_active, user.is_superuser = form.is_active.data, form.is_superuser.data
                if form.password.data:
                    user.set_password(form.password.data)
                user.auth_version += 1
                db.session.execute(update(TwoFactorCode).where(TwoFactorCode.user_id == user.id, TwoFactorCode.consumed_at.is_(None)).values(consumed_at=utcnow()))
                log_activity('UPDATE_ADMIN', f'Actualización de usuario id={user.id}; sesiones revocadas.')
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    flash('El correo o nombre de usuario ya existe.', 'error')
                    status = 400
                else:
                    flash('Cambios guardados. Se revocaron las sesiones del usuario.', 'success')
                    return redirect(url_for('admin.users_list'))
        else:
            status = 400
        if status != 200:
            db.session.rollback()
    return render_template('admin/user_edit.html', form=form, user=user), status


@admin_bp.post('/users/<int:id>/delete')
@fresh_login_required
def user_delete(id):
    require_superuser()
    supers = locked_superusers()
    user = db.session.scalar(db.select(User).where(User.id == id).with_for_update().execution_options(populate_existing=True))
    if user is None:
        abort(404)
    if user.is_active and user.is_superuser and len(supers) <= 1:
        db.session.rollback()
        flash('No se puede desactivar al último super administrador.', 'error')
        return redirect(url_for('admin.users_list'))
    user.is_active = False
    user.auth_version += 1
    log_activity('DEACTIVATE_ADMIN', f'Usuario id={id} desactivado; se conserva auditoría.')
    db.session.commit()
    flash('Administrador desactivado.', 'success')
    return redirect(url_for('admin.users_list'))


def audit_query():
    query = ActivityLog.query
    action = request.args.get('action', '')
    username = request.args.get('username', '')
    if action:
        if not re.fullmatch(r'[A-Z_]{1,64}', action):
            abort(400)
        query = query.filter(ActivityLog.action == action)
    if username:
        if len(username) > 64:
            abort(400)
        query = query.filter(ActivityLog.username == username)
    return query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())


@admin_bp.get('/logs')
@fresh_login_required
def view_logs():
    require_superuser()
    pagination = audit_query().paginate(page=max(1, request.args.get('page', 1, type=int)), per_page=50, error_out=False)
    return render_template('admin/logs.html', pagination=pagination)


@admin_bp.get('/logs/export')
@fresh_login_required
@limiter.limit('10 per hour')
def export_logs():
    require_superuser()
    query = audit_query()
    log_activity('EXPORT_AUDIT_CSV', 'Exportación de auditoría.')
    db.session.commit()

    def generate():
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['ID', 'Fecha UTC', 'Usuario', 'Acción', 'Detalles'])
        yield '\ufeff' + stream.getvalue()
        for row in query.yield_per(500):
            stream.seek(0)
            stream.truncate(0)
            writer.writerow([row.id, row.created_at.isoformat(), csv_safe(row.username), csv_safe(row.action), csv_safe(row.details)])
            yield stream.getvalue()

    return Response(stream_with_context(generate()), content_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="auditoria.csv"'})
