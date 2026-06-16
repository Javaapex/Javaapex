#!/usr/bin/env sh
set -eu

exec uvicorn main:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" \
  --limit-concurrency "${UVICORN_LIMIT_CONCURRENCY:-50}" \
  --limit-max-requests "${UVICORN_LIMIT_MAX_REQUESTS:-1000}" \
  --timeout-keep-alive "${UVICORN_TIMEOUT_KEEP_ALIVE:-300}" \
  --timeout-graceful-shutdown "${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-30}" \
  --h11-max-incomplete-event-size "${UVICORN_H11_MAX_INCOMPLETE_EVENT_SIZE:-1073741824}"
