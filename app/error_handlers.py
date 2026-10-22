import uuid
from flask import jsonify, render_template, request, current_app
from werkzeug.exceptions import HTTPException
from flask_wtf.csrf import CSRFError
from redis.exceptions import RedisError
from marshmallow import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from limits.errors import StorageError


def register_error_handlers(app):
    def respond(status, code, message, details=None):
        if request.path.startswith('/api/'):
            payload = {'error': message, 'code': code.lower()}
            if details:
                payload['details'] = details
            return jsonify(payload), status
        return render_template('errors.html', status=status, message=message), status

    @app.errorhandler(CSRFError)
    def csrf_error(_):
        return respond(400, 'CSRF_INVALID', 'La sesión de seguridad venció. Recargá la página y volvé a intentarlo.')

    @app.errorhandler(ValidationError)
    def validation_error(exc):
        return respond(422, 'VALIDATION_ERROR', 'Revisá los datos del formulario.', exc.messages)

    @app.errorhandler(RedisError)
    @app.errorhandler(StorageError)
    def redis_error(_):
        return respond(503, 'SERVICE_UNAVAILABLE', 'Servicio temporalmente no disponible. Intentá más tarde.')

    @app.errorhandler(SQLAlchemyError)
    def database_error(_):
        from app.extensions import db
        db.session.rollback()
        current_app.logger.error('database_unavailable')
        return respond(503, 'SERVICE_UNAVAILABLE', 'Servicio temporalmente no disponible. Intentá más tarde.')

    @app.errorhandler(HTTPException)
    def http_error(exc):
        messages = {400: 'Solicitud inválida.', 403: 'No tenés permiso para esta acción.', 404: 'No encontramos esa página.', 413: 'El formulario supera el tamaño permitido.', 429: 'Demasiados intentos. Esperá antes de volver a intentar.', 503: 'Servicio temporalmente no disponible.'}
        return respond(exc.code, exc.name.upper().replace(' ', '_'), messages.get(exc.code, exc.description))

    @app.errorhandler(Exception)
    def unexpected(exc):
        if current_app.testing:
            raise exc
        error_id = uuid.uuid4().hex
        current_app.logger.error('Unhandled error id=%s type=%s', error_id, type(exc).__name__)
        from app.extensions import db
        db.session.rollback()
        return respond(500, 'INTERNAL_ERROR', f'Ocurrió un error. Referencia: {error_id}')
