import os
import uuid
from urllib.parse import urlencode
from flask import Flask, g, request, jsonify, session
from flask_cors import CORS
from flask_wtf.csrf import generate_csrf
from werkzeug.middleware.proxy_fix import ProxyFix
from redis import Redis
from .config import build_config, validate_config
from .extensions import db, migrate, login_manager, csrf, mail, limiter, ma, talisman
from .error_handlers import register_error_handlers


def create_app(config_name=None, overrides=None):
    name = config_name or os.environ.get('FLASK_CONFIG', 'development')
    if name not in ('development', 'testing', 'production'):
        raise ValueError('FLASK_CONFIG must be development, testing or production')
    app = Flask(__name__, static_folder='../public', static_url_path='/public')
    app.config.update(build_config(name))
    app.config.update(overrides or {})
    validate_config(app)
    hops = app.config['TRUSTED_PROXY_COUNT']
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=0, x_port=0, x_prefix=0)
    app.extensions['redis'] = app.config.get('REDIS_CLIENT') or Redis.from_url(app.config['REDIS_URL'], socket_connect_timeout=2, socket_timeout=2)
    CORS(app, resources={r'/api/*': {'origins': app.config['CORS_ALLOWED_ORIGINS']}}, supports_credentials=True)
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    ma.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'
    login_manager.session_protection = 'strong'
    login_manager.login_message = 'Iniciá sesión para continuar.'
    limiter.init_app(app)
    csrf.init_app(app)
    talisman.init_app(app, force_https=False, session_cookie_secure=app.config['SESSION_COOKIE_SECURE'], content_security_policy={
        'default-src': "'self'", 'script-src': "'self'", 'style-src': "'self'", 'img-src': ["'self'", 'data:'], 'font-src': "'self'", 'frame-ancestors': "'none'", 'base-uri': "'self'", 'form-action': "'self'",
    }, referrer_policy='same-origin', strict_transport_security=name == 'production')

    @app.before_request
    def security_context():
        g.request_id = uuid.uuid4().hex
        if name == 'production' and request.path.startswith(('/api/', '/admin')):
            app.extensions['redis'].ping()

    @app.after_request
    def response_headers(response):
        response.headers['X-Request-ID'] = getattr(g, 'request_id', uuid.uuid4().hex)
        if request.path.startswith(('/api/', '/admin')):
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['Pragma'] = 'no-cache'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response

    @app.get('/api/csrf')
    def csrf_token():
        return jsonify(csrf_token=generate_csrf())

    @app.template_global()
    def pagination_url(page):
        args = request.args.to_dict(flat=True)
        args['page'] = page
        return request.path + '?' + urlencode(args)

    from .models.user import User
    from .models import audit, survey

    @login_manager.user_loader
    def load_user(user_id):
        if not str(user_id).isdigit():
            return None
        user = db.session.get(User, int(user_id))
        if not user or not user.is_active or session.get('auth_version') != user.auth_version:
            return None
        from .services.admin_session_service import valid_auth_session
        if not valid_auth_session(user):
            return None
        return user

    from .health import health_bp
    from .routes.admin import admin_bp
    from .routes.public import public_bp
    from .routes.simulation import simulation_bp
    app.register_blueprint(health_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(public_bp)
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    from .commands import create_admin, rotate_secret, seed_data, cleanup_survey
    for command in (create_admin, rotate_secret, seed_data, cleanup_survey):
        app.cli.add_command(command)
    register_error_handlers(app)
    return app
