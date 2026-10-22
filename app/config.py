import os
from datetime import timedelta
from urllib.parse import urlparse
from dotenv import load_dotenv


def boolean(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('true', '1', 'yes')


def is_https_origin(value):
    """CORS and cookie configuration require an origin, without URL paths."""
    try:
        parsed = urlparse(value)
        return (parsed.scheme == 'https' and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.path == '' and not parsed.params and not parsed.query
                and not parsed.fragment and '*' not in value
                and not any(character.isspace() for character in value)
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except (ValueError, TypeError):
        return False


def build_config(name):
    load_dotenv()
    testing = name == 'testing'
    production = name == 'production'
    database = os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URI')
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    settings = dict(
        ENVIRONMENT=name,
        TESTING=testing, DEBUG=name == 'development',
        SECRET_KEY=os.environ.get('SECRET_KEY') or ('testing-secret-only' if testing else None),
        IDENTITY_HMAC_KEY=os.environ.get('IDENTITY_HMAC_KEY') or ('testing-identity-key-only' if testing else None),
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:' if testing else database,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True, 'pool_recycle': 1800},
        REDIS_URL=redis_url,
        RATELIMIT_STORAGE_URI=redis_url if not testing else 'memory://',
        RATELIMIT_ENABLED=not testing,
        RATELIMIT_KEY_PREFIX=os.environ.get('RATELIMIT_KEY_PREFIX', ''),
        RATELIMIT_DEFAULT='200 per minute',
        RATELIMIT_HEADERS_ENABLED=True,
        RATELIMIT_SWALLOW_ERRORS=False,
        RATELIMIT_IN_MEMORY_FALLBACK_ENABLED=False,
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_TIME_LIMIT=4 * 3600,
        SESSION_COOKIE_NAME='survey_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
        SESSION_REFRESH_EACH_REQUEST=False,
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=production,
        REMEMBER_COOKIE_SAMESITE='Lax',
        MAX_CONTENT_LENGTH=32 * 1024,
        MAX_FORM_MEMORY_SIZE=32 * 1024,
        FRONTEND_URL=os.environ.get('FRONTEND_URL', 'http://localhost:5173').rstrip('/'),
        CORS_ALLOWED_ORIGINS=[o.strip() for o in os.environ.get('CORS_ORIGINS', os.environ.get('FRONTEND_URL', 'http://localhost:5173')).split(',') if o.strip()],
        TRUSTED_PROXY_COUNT=int(os.environ.get('TRUSTED_PROXY_COUNT', '0')),
        TRUSTED_HOSTS=[h.strip() for h in os.environ.get('TRUSTED_HOSTS', '').split(',') if h.strip()] or None,
        MAIL_SERVER=os.environ.get('MAIL_SERVER', 'localhost'),
        MAIL_PORT=int(os.environ.get('MAIL_PORT', '587')),
        MAIL_USE_TLS=boolean('MAIL_USE_TLS', True),
        MAIL_USE_SSL=boolean('MAIL_USE_SSL'),
        MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
        MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
        MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER'),
        MAIL_SUPPRESS_SEND=testing,
        MAIL_DEBUG=False,
        MAIL_TIMEOUT=int(os.environ.get('MAIL_TIMEOUT', '10')),
        ADMIN_OTP_TTL_SECONDS=600,
        ADMIN_OTP_MAX_ATTEMPTS=5,
        SURVEY_ID=os.environ.get('SURVEY_ID', 'lavalleja-2026'),
        SURVEY_TOKEN_TTL_SECONDS=int(os.environ.get('SURVEY_TOKEN_TTL_SECONDS', '86400')),
        SURVEY_COOKIE_SECURE=production,
        SURVEY_ENFORCE_IP_UNIQUENESS=boolean('SURVEY_ENFORCE_IP_UNIQUENESS', False),
        SURVEY_LINK_IP_LIMIT=os.environ.get('SURVEY_LINK_IP_LIMIT', '120 per hour;1000 per day'),
        SURVEY_CHALLENGE_IP_LIMIT=os.environ.get('SURVEY_CHALLENGE_IP_LIMIT', '120 per hour;1000 per day'),
        SURVEY_RESPONSE_IP_LIMIT=os.environ.get('SURVEY_RESPONSE_IP_LIMIT', '120 per hour;1000 per day'),
        SURVEY_CHALLENGE_TTL_SECONDS=300,
        SURVEY_CHALLENGE_MAX_ATTEMPTS=5,
        SURVEY_MIN_FILL_SECONDS=int(os.environ.get('SURVEY_MIN_FILL_SECONDS', '15' if production else '0')),
        TURNSTILE_REQUIRED=boolean('TURNSTILE_REQUIRED', False),
        TURNSTILE_SECRET_KEY=os.environ.get('TURNSTILE_SECRET_KEY', ''),
        TURNSTILE_SITE_KEY=os.environ.get('TURNSTILE_SITE_KEY', ''),
        TURNSTILE_HOSTNAME=os.environ.get('TURNSTILE_HOSTNAME', ''),
    )
    if testing:
        settings.update(WTF_CSRF_ENABLED=False, TURNSTILE_REQUIRED=False)
    return settings


def validate_config(app):
    c = app.config
    for key in ('SECRET_KEY', 'IDENTITY_HMAC_KEY', 'SQLALCHEMY_DATABASE_URI'):
        if not c.get(key):
            raise ValueError(f'{key} is required')
    if c['MAIL_USE_TLS'] and c['MAIL_USE_SSL']:
        raise ValueError('Choose MAIL_USE_TLS or MAIL_USE_SSL, not both')
    if c['MAIL_TIMEOUT'] <= 0:
        raise ValueError('MAIL_TIMEOUT must be a positive number of seconds')
    if bool(c['MAIL_USERNAME']) != bool(c['MAIL_PASSWORD']):
        raise ValueError('Configure both MAIL_USERNAME and MAIL_PASSWORD, or neither for an unauthenticated relay')
    if c['MAIL_PORT'] == 465 and not c['MAIL_USE_SSL']:
        raise ValueError('MAIL_PORT=465 requires MAIL_USE_SSL=true (implicit TLS)')
    if c['ENVIRONMENT'] != 'production':
        return
    for key in ('SECRET_KEY', 'IDENTITY_HMAC_KEY'):
        if len(c[key]) < 32 or c[key].startswith(('change', 'example', 'testing')):
            raise ValueError(f'{key} must be a unique random secret of at least 32 characters')
    if c['SECRET_KEY'] == c['IDENTITY_HMAC_KEY']:
        raise ValueError('Use independent SECRET_KEY and IDENTITY_HMAC_KEY')
    if not c['SQLALCHEMY_DATABASE_URI'].startswith('mariadb+mariadbconnector://'):
        raise ValueError('Production requires the MariaDB connector: mariadb+mariadbconnector://')
    if not c.get('REDIS_URL', '').startswith(('redis://', 'rediss://')):
        raise ValueError('Production requires REDIS_URL')
    if c.get('MAIL_SUPPRESS_SEND') or not c.get('MAIL_DEFAULT_SENDER') or not c.get('MAIL_SERVER'):
        raise ValueError('Production requires real SMTP configuration for admin 2FA')
    if not (c['MAIL_USE_TLS'] or c['MAIL_USE_SSL']):
        raise ValueError('Production SMTP must use TLS or SSL')
    if not is_https_origin(c['FRONTEND_URL']):
        raise ValueError('Production FRONTEND_URL must be an exact HTTPS origin without a path')
    if not c['CORS_ALLOWED_ORIGINS'] or any(not is_https_origin(origin) for origin in c['CORS_ALLOWED_ORIGINS']):
        raise ValueError('Production CORS must list exact HTTPS origins')
    if c['FRONTEND_URL'] not in c['CORS_ALLOWED_ORIGINS']:
        raise ValueError('CORS_ORIGINS must include FRONTEND_URL exactly')
    if not c.get('TRUSTED_HOSTS'):
        raise ValueError('Set TRUSTED_HOSTS to the frontend and backend hostnames')
    frontend_host = urlparse(c['FRONTEND_URL']).hostname
    if not any(frontend_host == host or (host.startswith('.') and
               (frontend_host == host[1:] or frontend_host.endswith(host)))
               for host in c['TRUSTED_HOSTS']):
        raise ValueError('TRUSTED_HOSTS must include the public FRONTEND_URL hostname')
    if c['TURNSTILE_REQUIRED'] and not all(c.get(k) for k in ('TURNSTILE_SECRET_KEY', 'TURNSTILE_SITE_KEY', 'TURNSTILE_HOSTNAME')):
        raise ValueError('TURNSTILE_SECRET_KEY, TURNSTILE_SITE_KEY and TURNSTILE_HOSTNAME are required')
    if c['SURVEY_MIN_FILL_SECONDS'] < 0:
        raise ValueError('SURVEY_MIN_FILL_SECONDS must not be negative')
    if not 60 <= c['SURVEY_CHALLENGE_TTL_SECONDS'] <= 600 or not 1 <= c['SURVEY_CHALLENGE_MAX_ATTEMPTS'] <= 10:
        raise ValueError('Built-in verification requires bounded expiry and attempts')
    if not 0 <= c['TRUSTED_PROXY_COUNT'] <= 3:
        raise ValueError('TRUSTED_PROXY_COUNT must match the real proxy chain (0-3)')
    from .utils.connector_security import verify_native_connector
    verify_native_connector()
