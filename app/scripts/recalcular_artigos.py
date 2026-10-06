#!/usr/bin/env python3
"""Recalcula a coluna `artigo` (e demais metadados jurídicos) dos chunks já
armazenados, SEM re-embedar.

Por quê existe:
  O `extract_article_num` antigo usava `(\\d+)`, que parava no ponto e lia
  "Art. 1.238" como artigo=1. Isso corrompeu 1.029 chunks do Código Civil
  (L10406compilada.pdf) e contaminou os documentos que o agregam (Vade Mecum).
  Corrigido o parser, os metadados já gravados continuam errados.

  Como o defeito é de METADADO (não de texto nem de vetor), não é preciso
  re-embedar: basta reler o `content` de cada chunk, recalcular os campos
  estruturados via `parse_chunk` e atualizar as colunas. Segundos, não horas.

Uso (de dentro do container app, que enxerga `db`):
  python3 scripts/recalcular_artigos.py [--dry-run] [--where "file_name ILIKE '%L10406%'"]

  --dry-run   apenas conta e mostra amostra do antes/depois, sem escrever
  --where     filtro SQL opcional para rodada parcial
  --limit     processar só os primeiros N (teste)
"""

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_DIR))

from database import get_db_connection  # noqa: E402
from legal_parser import parse_chunk  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("recalcular_artigos")


def main():
    parser = argparse.ArgumentParser(description="Recalcula metadados jurídicos sem re-embedar.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--where", type=str, default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    where_clause = ""
    params = []
    if args.where.strip():
        where_clause = f"WHERE {args.where.strip()}"
    if args.limit is not None:
        where_clause += (" WHERE" if not where_clause else " AND") + " id <= %s"
        params.append(args.limit)

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, content, file_name, artigo FROM documents {where_clause} ORDER BY id",
                params,
            )
            rows = cur.fetchall()

    total = len(rows)
    logger.info(f"{total} documentos para recalcular metadados.")

    mudancas = 0
    amostras = []
    updates = []  # (artigo, paragrafo, inciso, id)

    for doc_id, content, file_name, artigo_antigo in rows:
        meta = parse_chunk(content or "", file_name or "")
        artigo_novo = meta.get("artigo")
        if artigo_novo != artigo_antigo:
            mudancas += 1
            if len(amostras) < 10:
                amostras.append((doc_id, file_name, artigo_antigo, artigo_novo))
        updates.append((artigo_novo, meta.get("paragrafo"), meta.get("inciso"), doc_id))

    logger.info(f"Mudanças de `artigo`: {mudancas}/{total}")
    for doc_id, file_name, antes, depois in amostras:
        logger.info(f"  id={doc_id} {file_name}: artigo {antes} -> {depois}")

    if args.dry_run:
        logger.info("[dry-run] nada foi escrito.")
        return

    # Atualiza em lotes, numa transação por lote.
    processados = 0
    for i in range(0, len(updates), args.batch_size):
        batch = updates[i:i + args.batch_size]
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for artigo, paragrafo, inciso, doc_id in batch:
                    cur.execute(
                        "UPDATE documents SET artigo = %s, paragrafo = %s, inciso = %s WHERE id = %s",
                        (artigo, paragrafo, inciso, doc_id),
                    )
                conn.commit()
        processados += len(batch)
        logger.info(f"Atualizado {processados}/{total}.")

    logger.info(f"Concluído: {processados} documentos recalculados ({mudancas} com mudança de artigo).")


if __name__ == "__main__":
    main()
