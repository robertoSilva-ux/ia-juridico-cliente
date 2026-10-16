#!/usr/bin/env python3
"""Smoke test do ambiente de DESENVOLVIMENTO (sem Docker).

Exercita o caminho completo que a interface usa, sem subir o Streamlit:

    banco (podman)  ->  ingestão  ->  recuperação  ->  Ollama (embeddings + LLM)  ->  fact-check

Ele valida o AMBIENTE, não a qualidade do modelo: falha se o Ollama não
responder, se o banco estiver inacessível, se nada for recuperado ou se a
resposta vier vazia. Se o modelo acertar o dado do contexto, isso é reportado
como observação (não como falha) — julgamento de qualidade é papel do avaliador
(`app/eval/run_eval.py`), não do smoke test.

Uso:
    set -a; . ./.env.dev; set +a
    .venv/bin/python scripts/smoke_dev.py
"""
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import requests  # noqa: E402
from agent import get_response  # noqa: E402
from auth import add_user, get_user_id  # noqa: E402
from embeddings import NomicOllamaEmbeddings  # noqa: E402
from ingest import store_in_postgres  # noqa: E402

from database import get_db_connection  # noqa: E402

ARQUIVO = "Lei 8.213-91.pdf"
# E-mail válido para o validate_email do auth (exige TLD). Se o usuário não for
# criado, o teste FALHA: rodar com user_id=None desliga o filtro de escopo do
# agente (ver P2-15 no backlog) e não é o caminho que a interface usa.
EMAIL_DEV = "dev@legaliz.local"
SENHA_DEV = "senha-de-dev-123"
PERGUNTA = "Qual é a carência exigida para a concessão do benefício?"
DADO_ESPERADO = "180"          # observação, não critério de falha

CHUNKS = [
    "Art. 25. A carência exigida para a concessão do benefício é de 180 contribuições mensais.",
    "Art. 54. A aposentadoria por tempo de contribuição será devida ao segurado que cumprir "
    "35 anos de contribuição, se homem, e 30 anos, se mulher.",
]


class Chunk:
    """Interface mínima de chunk esperada por store_in_postgres."""

    def __init__(self, texto):
        self.page_content = texto
        self.metadata = {"origem": "smoke_dev"}


def _mascarar(dsn: str) -> str:
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", dsn or "")


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    ollama = os.environ.get("OLLAMA_BASE_URL", "")
    modelo = os.environ.get("LLM_MODEL", "")
    print(f"banco:  {_mascarar(db_url)}")
    print(f"ollama: {ollama} (modelo: {modelo})")

    if not db_url:
        print("✘ DATABASE_URL não definida — carregue o .env.dev (set -a; . ./.env.dev; set +a)")
        return 1

    # 1. Ollama de pé?
    try:
        v = requests.get(f"{ollama.rstrip('/')}/api/version", timeout=5).json()
        print(f"[ok] Ollama respondendo ({v.get('version')})")
    except Exception as e:
        print(f"✘ Ollama não respondeu em {ollama}: {e}")
        return 1

    # 2. Banco acessível e usuário de dev
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as e:
        print(f"✘ banco inacessível ({_mascarar(db_url)}): {e}")
        return 1
    ok, msg = add_user(EMAIL_DEV, "Desenvolvimento Local", SENHA_DEV, "admin")
    if not ok:
        print(f"✘ não foi possível criar/validar o usuário de dev: {msg.strip()}")
        return 1
    print(f"[ok] usuário de dev: {msg.strip()}")
    user_id = get_user_id(EMAIL_DEV)
    if user_id is None:
        print("✘ usuário de dev não encontrado — o teste precisa de user_id para exercitar o filtro de escopo")
        return 1

    # 3. Ingestão com embeddings reais
    embedder = NomicOllamaEmbeddings(
        model=os.environ.get("EMBEDDING_MODEL", "nomic-embed-text"),
        base_url=ollama,
    )
    t0 = time.time()
    for _ in store_in_postgres([Chunk(c) for c in CHUNKS], embedder, ARQUIVO,
                               owner_id=None, scope="global", batch_size=10):
        pass
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents WHERE file_name = %s", (ARQUIVO,))
            indexados = cur.fetchone()[0]
    print(f"[ok] ingestão de '{ARQUIVO}': {indexados} chunk(s) na base ({time.time()-t0:.1f}s)")
    if not indexados:
        print("✘ nada indexado")
        return 1

    # 4. Pergunta ponta a ponta (recuperação + LLM + fact-check)
    t0 = time.time()
    resultado = get_response(PERGUNTA, user_id=user_id, user_email=EMAIL_DEV)
    dt = time.time() - t0
    resposta = resultado.get("answer") or ""
    fontes = resultado.get("sources") or []
    fc = resultado.get("fact_check") or {}

    print(f"\n--- pergunta: {PERGUNTA}")
    print(f"--- resposta ({dt:.1f}s, {len(fontes)} fonte(s)) ---")
    print(resposta.strip()[:800])
    for s in fontes:
        print(f"    [{s['ref']}] {s['source_label']}  distância={s['distance']:.3f}")
    print("--- fact-check:", {k: fc.get(k) for k in
                              ("total_sentences", "supported", "partial", "no_support", "all_grounded")})

    if not fontes:
        print("\n✘ nenhuma fonte recuperada — recuperação não está funcionando")
        return 1
    if not resposta.strip():
        print("\n✘ resposta vazia")
        return 1

    if DADO_ESPERADO in resposta:
        print(f"\n[ok] o modelo citou o dado do contexto ({DADO_ESPERADO})")
    else:
        print(f"\n[obs] o modelo não citou {DADO_ESPERADO} — o contexto foi recuperado, "
              "então isto é qualidade do modelo/prompt, não do ambiente "
              "(use app/eval/run_eval.py para medir)")

    print("\n>>> AMBIENTE DE DESENVOLVIMENTO OK: banco, embeddings, recuperação e LLM funcionando")
    return 0


if __name__ == "__main__":
    sys.exit(main())
