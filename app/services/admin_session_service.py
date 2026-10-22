import secrets
from flask import current_app, session
from redis.exceptions import RedisError
from app.utils.security import digest


def _key(nonce):
    return 'admin-auth:' + digest(nonce)


def create_auth_session(user):
    nonce = secrets.token_urlsafe(32)
    ttl = int(current_app.permanent_session_lifetime.total_seconds())
    current_app.extensions['redis'].set(_key(nonce), f'{user.id}:{user.auth_version}', ex=ttl)
    session['auth_nonce'] = nonce


def valid_auth_session(user):
    nonce = session.get('auth_nonce')
    if not isinstance(nonce, str) or len(nonce) != 43:
        return False
    try:
        actual = current_app.extensions['redis'].get(_key(nonce))
    except RedisError:
        # Fail closed even when called while rendering an outage error page.
        return False
    expected = f'{user.id}:{user.auth_version}'.encode()
    return actual == expected or actual == expected.decode()


def revoke_auth_session():
    nonce = session.pop('auth_nonce', None)
    if nonce:
        current_app.extensions['redis'].delete(_key(nonce))
