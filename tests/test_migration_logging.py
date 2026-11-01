"""Migrations must preserve diagnostics in the application process."""
import io
import logging
from pathlib import Path

import fakeredis

from app import create_app
from app.extensions import db


def test_migrations_preserve_application_error_logging(tmp_path):
    database_path = (tmp_path / 'migration-logging.sqlite').as_posix()
    app = create_app('testing', {
        'REDIS_CLIENT': fakeredis.FakeRedis(),
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path}',
    })
    logger = app.logger
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    try:
        result = app.test_cli_runner().invoke(args=['db', 'upgrade', '-d', migrations])
        assert result.exit_code == 0, result.output
        # Attach after migration because fileConfig replaces root handlers.
        # A disabled application logger would still silently discard this error.
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logger.addHandler(handler)
        try:
            logger.error('migration-logging-regression-probe')
        finally:
            logger.removeHandler(handler)
            handler.close()
        assert not logger.disabled
        assert 'migration-logging-regression-probe' in output.getvalue()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
