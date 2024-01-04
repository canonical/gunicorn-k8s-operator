#!/bin/bash
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

exec gunicorn "${APP_WSGI:-app:app}" \
  --name="${APP_NAME:-my-awesome-app}" \
  --bind=0.0.0.0:8080 \
  --workers="${APP_WORKERS:-1}" \
  --worker-class="${WORKER_CLASS:-sync}" \
  --worker-connections="${WORKER_CONNECTIONS:-1000}" \
  --backlog="${BACKLOG:-2048}" \
  --max-requests="${MAX_REQUESTS:-0}" \
  --timeout="${TIMEOUT:-30}" \
  --graceful-timeout="${GRACEFUL_TIMEOUT:-30}" \
  --keep-alive="${KEEPALIVE:-2}" \
  --pythonpath=/srv/gunicorn/ \
  --proxy-allow-from='*' \
  --log-file="${LOGFILE:--}" \
  --access-logfile="${ACCESS_LOGFILE:--}" \
  --access-logformat="${ACCESS_LOGFORMAT:-%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s}" \
  --statsd-host=localhost:9125 \
  --statsd-prefix=statsd_data
