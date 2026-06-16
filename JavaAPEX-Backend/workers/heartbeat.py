"""Worker heartbeat helpers for queued migration execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from utils.config import WORKER_HEARTBEAT_INTERVAL_SEC


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    job_id: str
    emitted_at: datetime
    interval_seconds: int = WORKER_HEARTBEAT_INTERVAL_SEC


def get_worker_id() -> str:
    return (os.environ.get("HOSTNAME") or os.environ.get("COMPUTERNAME") or "worker").strip()


def build_worker_heartbeat(job_id: str) -> WorkerHeartbeat:
    return WorkerHeartbeat(
        worker_id=get_worker_id(),
        job_id=job_id,
        emitted_at=datetime.now(timezone.utc),
    )

