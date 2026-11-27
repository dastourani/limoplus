#!/bin/sh
# Start script for ParsPack PaaS (and any Python "source-to-image" host): it runs this file instead of gunicorn alone.
# Every start: apply database changes, gather the panel's and the website's static files, then serve.
set -e
cd "$(dirname "$0")"
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
export _LIMO_STARTUP_DONE=1
exec gunicorn -c gunicorn.conf.py
