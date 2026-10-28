#!/bin/sh
set -e

if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
    echo "Applying database migrations..."
    python manage.py migrate --noinput
fi

exec "$@"
