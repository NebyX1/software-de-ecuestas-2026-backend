from flask import current_app, g, request
from flask_wtf.csrf import CSRFProtect, same_origin, validate_csrf
from wtforms import ValidationError


class ApiCSRFProtect(CSRFProtect):
    """Allow configured frontend origins on API requests, keeping admin strict."""

    def protect(self):
        if not request.path.startswith('/api/'):
            return super().protect()
        if request.method not in current_app.config['WTF_CSRF_METHODS']:
            return
        try:
            validate_csrf(self._get_csrf_token())
        except ValidationError as error:
            self._error_response(error.args[0])

        origins = {*current_app.config['CORS_ALLOWED_ORIGINS'], request.host_url.rstrip('/')}
        origin = request.headers.get('Origin')
        if origin is not None and origin not in origins:
            self._error_response('The origin is not allowed.')
        if request.is_secure and current_app.config['WTF_CSRF_SSL_STRICT']:
            if not request.referrer or not any(same_origin(request.referrer, allowed) for allowed in origins):
                self._error_response('The referrer is not allowed.')
        g.csrf_valid = True
