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

from legal_parser import build_title, parse_file_name  # noqa: E402

from database import get_db_connection  # noqa: E402


def _get_or_create_source(cur, file_name, owner_id=None, scope='global'):
    """Upsert da fonte por (file_name, dono) — nunca só pelo nome do arquivo.

    O backfill antigo resolvia o conflito por `file_name`, com
    `owner_id = COALESCE(EXCLUDED.owner_id, sources.owner_id)`: ao encontrar um
    arquivo homônimo de outro dono, ele reescrevia o dono da fonte existente —
    fonte de um tenant passando a pertencer a outro (docs/REVISAO_SEGURANCA.md, P0-4).

    O dono entra como `COALESCE(owner_id, -1)` porque NULL é distinto de NULL em
    índice único; sem isso o conflito não casaria para as cargas sem dono
    (--owner-id None) e cada execução criaria uma linha nova de fonte. O alvo tem
    de ser escrito igual ao índice `sources_file_owner_uidx` (database/init.sql).
    """
    meta = parse_file_name(file_name)
    title = build_title(meta)
    cur.execute(
        "INSERT INTO sources (file_name, title, tipo_doc, numero_doc, ano_doc, owner_id, scope) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (file_name, (COALESCE(owner_id, -1))) DO UPDATE SET "
        "    title = COALESCE(EXCLUDED.title, sources.title), "
        "    tipo_doc = COALESCE(EXCLUDED.tipo_doc, sources.tipo_doc), "
        "    numero_doc = COALESCE(EXCLUDED.numero_doc, sources.numero_doc), "
        "    ano_doc = COALESCE(EXCLUDED.ano_doc, sources.ano_doc), "
        "    scope = EXCLUDED.scope "
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
            # Agrupa por (arquivo, DONO): a fonte é por dono, então o backfill e o
            # vínculo dos chunks precisam ser resolvidos dentro de cada dono.
            cur.execute(
                "SELECT file_name, owner_id, COALESCE(MAX(scope), 'global') "
                "FROM documents WHERE file_name IS NOT NULL "
                "GROUP BY file_name, owner_id "
                "ORDER BY file_name, owner_id"
            )
            rows = cur.fetchall()
            print('pares (arquivo, dono) distintos: ' + str(len(rows)))
            created = 0
            for fn, owner_id, scope in rows:
                sid = _get_or_create_source(cur, fn, owner_id=owner_id, scope=scope)
                if sid:
                    created += 1
                    if not args.dry_run:
                        cur.execute(
                            "UPDATE documents SET source_id = %s "
                            "WHERE file_name = %s AND owner_id IS NOT DISTINCT FROM %s "
                            "AND source_id IS NULL",
                            (sid, fn, owner_id),
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
