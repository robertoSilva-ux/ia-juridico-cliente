import os
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:***@db:5432/legal_db")


def log_question(user_id: int, user_email: str, question: str, response_summary: str, sources: list):
    """Registra uma pergunta no audit_log."""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (user_id, user_email, question, response_summary, sources_used)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (user_id, user_email, question, response_summary[:500], sources)
                )
                conn.commit()
    except Exception as e:
        # Não deve interromper o fluxo do chat se o log falhar
        import logging
        logging.error(f"Erro ao registrar auditoria: {e}")


def get_audit_logs(
    user_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
    offset: int = 0
) -> list[dict[str, Any]]:
    """Busca logs de auditoria com filtros opcionais."""
    conditions = []
    params = []

    if user_email:
        conditions.append("a.user_email = %s")
        params.append(user_email)

    if date_from:
        conditions.append("a.created_at >= %s")
        params.append(date_from)

    if date_to:
        conditions.append("a.created_at <= %s")
        params.append(date_to)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sql = f"""
        SELECT
            a.id,
            a.user_email,
            a.question,
            a.response_summary,
            a.sources_used,
            a.created_at,
            u.name AS user_name
        FROM audit_log a
        LEFT JOIN users u ON a.user_id = u.id
        WHERE {where_clause}
        ORDER BY a.created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def count_audit_logs(
    user_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None
) -> int:
    """Conta total de registros com os filtros aplicados."""
    conditions = []
    params = []

    if user_email:
        conditions.append("user_email = %s")
        params.append(user_email)

    if date_from:
        conditions.append("created_at >= %s")
        params.append(date_from)

    if date_to:
        conditions.append("created_at <= %s")
        params.append(date_to)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sql = f"SELECT COUNT(*) as total FROM audit_log WHERE {where_clause}"

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]


def get_unique_users_from_audit() -> list[str]:
    """Retorna lista de emails únicos que já fizeram perguntas."""
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT user_email FROM audit_log ORDER BY user_email")
            return [row[0] for row in cur.fetchall()]
