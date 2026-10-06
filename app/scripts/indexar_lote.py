"""Indexação em massa com progresso agregado e N workers.

Substitui o par `process_pdf` + reindexação sequencial por um único caminho que
serve tanto o upload de UM arquivo quanto uma rodada em LOTE — usando o mesmo
`progress.run_parallel`, o que permite à UI manter uma barra única.

Design:
  - Cada item do lote é um (caminho, nome) de arquivo.
  - Peso de cada item = tamanho do arquivo (MB), porque o custo é proporcional
    ao volume de texto, não ao número de arquivos. Sem isso, um PDF de 200 MB e
    um de 0.5 MB contariam igual e a barra mentiria.
  - Falha num arquivo não interrompe o lote; o erro é coletado e reportado.
  - `workers=1` dá exatamente o comportamento sequencial (mesmo código).
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

# Garante que os módulos (`ingest`, `progress`, `config`) sejam importáveis.
# Caso 1 (container): script em /app/scripts, módulos em /app.
# Caso 2 (host): script em app/scripts, módulos em app/.
SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_DIR))

from config import EMBED_BATCH_SIZE, EMBEDDING_MODEL, OLLAMA_BASE_URL  # noqa: E402
from embeddings import NomicOllamaEmbeddings  # noqa: E402
from ingest import ingest_document  # noqa: E402
from progress import DEFAULT_WORKERS, run_parallel  # noqa: E402

logger = logging.getLogger(__name__)


def _peso_mb(caminho: str) -> float:
    """Peso do item = tamanho em MB (mínimo 0.1 para não zerar)."""
    try:
        return max(os.path.getsize(caminho) / (1024 * 1024), 0.1)
    except OSError:
        return 0.1


def indexar_lote(
    arquivos: Sequence[tuple[str, str]],
    *,
    owner_id: int | None = None,
    scope: str = 'global',
    workers: int = DEFAULT_WORKERS,
    batch_size: int = EMBED_BATCH_SIZE,
    progress_cb: Callable[[float], None] | None = None,
    item_cb: Callable[[int, str, str | None], None] | None = None,
) -> dict:
    """Indexa uma lista de ``(caminho, nome)`` com ``workers`` threads.

    Args:
        arquivos: pares ``(caminho_no_disco, nome_logico)``.
        owner_id: dono dos documentos (None = global).
        scope: 'global' ou 'private'.
        workers: threads. 2 é o ótimo medido (Ollama serializa na GPU).
        batch_size: chunks por chamada a /api/embed.
        progress_cb: recebe 0.0->1.0 do lote inteiro.
        item_cb: recebe ``(index, nome, erro_ou_None)`` ao concluir cada arquivo.

    Returns:
        ``{"ok": n, "falhas": [(nome, erro)], "chunks": n_total}``.
    """
    if not arquivos:
        if progress_cb is not None:
            progress_cb(1.0)
        return {"ok": 0, "falhas": [], "chunks": 0}

    pesos = [_peso_mb(caminho) for caminho, _ in arquivos]
    embedder = NomicOllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_BASE_URL)

    falhas: list[tuple[str, str]] = []
    chunks_total = 0

    def _worker(index: int, item: tuple[str, str], set_fraction: Callable[[float], None]):
        caminho, nome = item
        return ingest_document(
            caminho,
            embedder,
            nome,
            owner_id=owner_id,
            scope=scope,
            batch_size=batch_size,
            progress_cb=set_fraction,
        )

    def _on_result(index, item, result, error):
        nonlocal chunks_total
        _, nome = item
        if error is not None:
            falhas.append((nome, str(error)))
            logger.error(f"[{index + 1}/{len(arquivos)}] FALHA {nome}: {error}")
        else:
            chunks_total += int(result or 0)
            logger.info(f"[{index + 1}/{len(arquivos)}] OK {nome} -> {result} chunks")
        if item_cb is not None:
            item_cb(index, nome, None if error is None else str(error))

    run_parallel(
        arquivos,
        _worker,
        workers=workers,
        weights=pesos,
        on_progress=progress_cb,
        on_result=_on_result,
    )

    return {
        "ok": len(arquivos) - len(falhas),
        "falhas": falhas,
        "chunks": chunks_total,
    }


def _main() -> None:
    """CLI para indexação em massa headless.

    Uso (dentro do container app):
      python3 scripts/indexar_lote.py ARQ1 [ARQ2 ...] [--name NOME] [--workers 2]
      python3 scripts/indexar_lote.py --lista arquivos.txt [--workers 2]

    Cada linha de ``--lista`` é ``caminho<TAB>nome`` (TAB) ou só o caminho
    (o nome lógico vira o basename).
    """
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Indexação em massa com progresso agregado.")
    parser.add_argument("arquivos", nargs="*", help="caminhos dos arquivos")
    parser.add_argument("--lista", help="arquivo texto com um caminho por linha")
    parser.add_argument("--name", help="nome lógico (só com um arquivo)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--scope", default="global", choices=["global", "private"])
    parser.add_argument("--owner-id", type=int, default=None)
    args = parser.parse_args()

    itens: list[tuple[str, str]] = []
    if args.lista:
        with open(args.lista, encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.rstrip("\n")
                if not linha.strip():
                    continue
                if "\t" in linha:
                    caminho, nome = linha.split("\t", 1)
                else:
                    caminho, nome = linha, os.path.basename(linha)
                itens.append((caminho, nome))
    for caminho in args.arquivos:
        itens.append((caminho, args.name or os.path.basename(caminho)))

    if not itens:
        parser.error("nenhum arquivo informado (use posicionais ou --lista)")

    ultimo = [-1]

    def _progresso(f: float) -> None:
        pct = int(f * 100)
        if pct != ultimo[0]:
            ultimo[0] = pct
            print(f"  progresso: {pct}%", flush=True)

    resultado = indexar_lote(
        itens,
        owner_id=args.owner_id,
        scope=args.scope,
        workers=args.workers,
        progress_cb=_progresso,
    )

    print(f"\nConcluído: {resultado['ok']}/{len(itens)} arquivos, {resultado['chunks']} chunks.")
    if resultado["falhas"]:
        print(f"FALHAS ({len(resultado['falhas'])}):")
        for nome, erro in resultado["falhas"]:
            print(f"  - {nome}: {erro}")
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
