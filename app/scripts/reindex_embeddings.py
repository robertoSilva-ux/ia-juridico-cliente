#!/usr/bin/env python3
"""Reindexa a coluna `embedding` da tabela `documents` com os prefixos
assimétricos do nomic-embed-text (search_document:).

Por quê existe:
  O nomic-embed-text espera `search_document: ` ao vetorizar documentos e
  `search_query: ` ao vetorizar consultas. Os vetores atuais foram gerados SEM
  prefixo; após ativar o wrapper NomicOllamaEmbeddings (app/embeddings.py), a
  base antiga fica desalinhada e a busca degrada. Este script regenera todos
  os vetores com o prefixo correto.

Uso (de dentro do container app, que enxerga `db` e `ollama`):
  python3 scripts/reindex_embeddings.py [--batch-size N] [--limit N]

  --batch-size   tamanho do lote p/ o /api/embed (default 128)
  --limit        reindexar só os primeiros N documentos (teste), sem flag = todos
  --dry-run      apenas conta/lista os docs afetados, sem reescrever nada
  --where        filtro SQL opcional p/ rodada parcial (ex.: "owner_id = 1")

Exemplos:
  python3 scripts/reindex_embeddings.py --dry-run
  python3 scripts/reindex_embeddings.py --limit 20
  python3 scripts/reindex_embeddings.py
"""

import argparse
import logging
import sys
from pathlib import Path

# Garante que os módulos (`database`, `embeddings`, `config`) sejam importáveis.
# Caso 1 (container): script em /app/scripts, módulos em /app.
# Caso 2 (host): script em app/scripts, módulos em app/.
SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_DIR))

from config import EMBED_BATCH_SIZE, EMBEDDING_MODEL, OLLAMA_BASE_URL  # noqa: E402
from database import get_db_connection  # noqa: E402
from embeddings import NomicOllamaEmbeddings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reindex")


def main():
    parser = argparse.ArgumentParser(description="Reindexa embeddings com prefixo nomic-embed-text.")
    parser.add_argument("--batch-size", type=int, default=EMBED_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--where", type=str, default="")
    args = parser.parse_args()

    embeddings = NomicOllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_BASE_URL)

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            where_clause = ""
            params = []
            if args.where.strip():
                where_clause = f"WHERE {args.where.strip()}"
            if args.limit is not None:
                where_clause += (" WHERE" if not where_clause else " AND") + " id <= %s"
                params.append(args.limit)

            # Busca id + content (texto cru, sem prefixo) de todos os docs.
            cur.execute(f"SELECT id, content FROM documents {where_clause} ORDER BY id", params)
            rows = cur.fetchall()

    total = len(rows)
    logger.info(f"{total} documentos para reindexar. prefixo='search_document: '")

    if args.dry_run:
        for doc_id, content in rows[:10]:
            logger.info(f"  [dry-run] id={doc_id} preview={content[:60]!r}...")
        logger.info(f"[dry-run] {total} docs encontrados; nada foi escrito.")
        return

    processed = 0
    for i in range(0, total, args.batch_size):
        batch = rows[i:i + args.batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]

        # Gera vetores com prefixo (o wrapper já aplica `search_document:`).
        vectors = embeddings.embed_documents(texts)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for doc_id, vec in zip(ids, vectors, strict=True):
                    cur.execute(
                        "UPDATE documents SET embedding = %s::vector WHERE id = %s",
                        (vec, doc_id),
                    )
                conn.commit()

        processed += len(batch)
        logger.info(f"Reindexado {processed}/{total} docs.")

    logger.info(f"Concluído: {processed} documentos reindexados.")


if __name__ == "__main__":
    main()
