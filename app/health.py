from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from app.extensions import db
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

health_bp = Blueprint('health', __name__)


@health_bp.get('/health/live')
def live():
    return jsonify(status='ok')


@health_bp.get('/health/ready')
@health_bp.get('/health')
def ready():
    database = redis_ok = schema = False
    try:
        db.session.execute(text('SELECT 1'))
        database = True
        migration_config = Config()
        migration_config.set_main_option('script_location', str(Path(current_app.root_path).parent / 'migrations'))
        expected = set(ScriptDirectory.from_config(migration_config).get_heads())
        actual = set(db.session.execute(text('SELECT version_num FROM alembic_version')).scalars())
        schema = bool(expected) and actual == expected
    except Exception:
        db.session.rollback()
    try:
        redis_ok = bool(current_app.extensions['redis'].ping())
    except Exception:
        pass
    status = 200 if database and redis_ok and schema else 503
    return jsonify(status='ok' if status == 200 else 'unavailable', database=database, redis=redis_ok, schema=schema), status
