"""Pool de conexões PostgreSQL centralizado."""
import logging
from contextlib import contextmanager

from pgvector.psycopg2 import register_vector
from psycopg2.pool import SimpleConnectionPool

from config import DATABASE_URL, DB_CONNECT_TIMEOUT, DB_POOL_MAX, DB_POOL_MIN, IVFFLAT_PROBES

logger = logging.getLogger(__name__)

db_pool = SimpleConnectionPool(
    minconn=DB_POOL_MIN,
    maxconn=DB_POOL_MAX,
    dsn=DATABASE_URL,
    connect_timeout=DB_CONNECT_TIMEOUT
)


@contextmanager
def get_db_connection():
    conn = None
    try:
        conn = db_pool.getconn()
        register_vector(conn)
        with conn.cursor() as _cur:
            _cur.execute("SET ivfflat.probes = %s", (IVFFLAT_PROBES,))
        yield conn
    finally:
        if conn:
            db_pool.putconn(conn)


@contextmanager
def get_db_cursor(cursor_factory=None):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur
