#!/usr/bin/env sh
set -eu

exec python -m celery \
  -A services.celery_app:celery_app \
  worker \
  --loglevel "${CELERY_LOG_LEVEL:-info}" \
  --concurrency "${MIGRATION_MAX_CONCURRENT_JOBS:-1}" \
  --prefetch-multiplier "${CELERY_PREFETCH_MULTIPLIER:-1}" \
  -Q "${CELERY_WORKER_QUEUES:-migration-core,migration-tests,migration-scans}"
