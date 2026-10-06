#!/usr/bin/env python3
"""Backfill da Task 7: popula `sources` e preenche `source_id` nos chunks
existentes, SEM re-embedar.

Uso (dentro do container app): python3 scripts/backfill_sources.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_DIR))

from database import get_db_connection  # noqa: E402
from legal_parser import build_title, parse_file_name  # noqa: E402


def _get_or_create_source(cur, file_name, owner_id=None, scope='global'):
    meta = parse_file_name(file_name)
    title = build_title(meta)
    cur.execute(
        "INSERT INTO sources (file_name, title, tipo_doc, numero_doc, ano_doc, owner_id, scope) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (file_name) DO UPDATE SET "
        "    title = COALESCE(EXCLUDED.title, sources.title), "
        "    tipo_doc = COALESCE(EXCLUDED.tipo_doc, sources.tipo_doc), "
        "    numero_doc = COALESCE(EXCLUDED.numero_doc, sources.numero_doc), "
        "    ano_doc = COALESCE(EXCLUDED.ano_doc, sources.ano_doc), "
        "    owner_id = COALESCE(EXCLUDED.owner_id, sources.owner_id), "
        "    scope = COALESCE(EXCLUDED.scope, sources.scope) "
        "RETURNING id",
        (file_name, title, meta['tipo'], meta['numero'], meta['ano'], owner_id, scope),
    )
    row = cur.fetchone()
    return row[0] if row else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_name, MAX(owner_id), COALESCE(MAX(scope), 'global') "
                "FROM documents WHERE file_name IS NOT NULL GROUP BY file_name "
                "ORDER BY file_name"
            )
            rows = cur.fetchall()
            print('file_names distintos: ' + str(len(rows)))
            created = 0
            for fn, owner_id, scope in rows:
                sid = _get_or_create_source(cur, fn, owner_id=owner_id, scope=scope)
                if sid:
                    created += 1
                    if not args.dry_run:
                        cur.execute(
                            "UPDATE documents SET source_id = %s "
                            "WHERE file_name = %s AND source_id IS NULL",
                            (sid, fn),
                        )
            if args.dry_run:
                print('DRY-RUN: nada escrito.')
            else:
                conn.commit()
                print('sources criadas/atualizadas: ' + str(created))
            cur.execute('SELECT count(*) FROM sources')
            total_sources = cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM documents WHERE source_id IS NOT NULL')
            total_linked = cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM documents')
            total_docs = cur.fetchone()[0]
            print('sources total: ' + str(total_sources) + ' | chunks com source_id: ' + str(total_linked) + '/' + str(total_docs))


if __name__ == '__main__':
    main()
