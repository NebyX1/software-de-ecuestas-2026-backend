#!/bin/sh
set -eu
# Apply migrations once as a release command before scaling workers/replicas.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    python -m flask --app wsgi:app db upgrade -d migrations
fi
exec gunicorn --config gunicorn.conf.py wsgi:app
