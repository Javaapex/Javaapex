"""PostgreSQL connection pool for the JavaAPEX platform."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "javaapex")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_SCHEMA = os.environ.get("DB_SCHEMA", "apex")

_pool = None


def _get_pool():
    """Lazily create and return a psycopg2 connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    try:
        from psycopg2 import pool
        from psycopg2.extras import RealDictCursor

        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            options=f"-c search_path={DB_SCHEMA},public",
        )
        logger.info(
            "PostgreSQL connection pool created host=%s port=%s db=%s schema=%s",
            DB_HOST,
            DB_PORT,
            DB_NAME,
            DB_SCHEMA,
        )
        return _pool
    except Exception:
        logger.exception("Failed to create PostgreSQL connection pool")
        return None


@contextmanager
def get_connection() -> Generator:
    """Yield a database connection from the pool.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    pool = _get_pool()
    if pool is None:
        raise RuntimeError("Database connection pool is not available")

    conn = None
    try:
        conn = pool.getconn()
        yield conn
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn and pool:
            pool.putconn(conn)


@contextmanager
def get_cursor(commit: bool = True) -> Generator:
    """Yield a dictionary cursor from a pooled connection.

    Usage:
        with get_cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
    """
    with get_connection() as conn:
        from psycopg2.extras import RealDictCursor

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                yield cur
                if commit:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise


def is_database_available() -> bool:
    """Check whether the database connection can be established."""
    try:
        with get_cursor(commit=False) as cur:
            cur.execute("SELECT 1")
            return True
    except Exception:
        return False