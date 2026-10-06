"""Framework de progresso agregado para trabalho paralelo.

Motivação: a ingestão de um arquivo reporta progresso linear (0.0 -> 1.0) via
generator. Com N workers em paralelo, esse sinal deixa de ser suficiente — é
preciso saber quanto do TRABALHO TOTAL já foi concluído, não quanto de cada
tarefa isolada.

Este módulo oferece:

  ProgressTracker  — contador compartilhado e thread-safe. Cada worker registra
                     frações concluídas; ``snapshot()`` devolve o progresso
                     global (0.0 -> 1.0). Suporta pesos por unidade de trabalho,
                     porque os itens não têm todos o mesmo custo.

  run_parallel     — executa uma função sobre N itens com W workers, mantendo o
                     MESMO caminho de código do caso sequencial (W=1). É esse
                     unificador que permite à barra do Streamlit servir tanto o
                     upload de um arquivo quanto uma reindexação em massa.

Por que threads e não processos: o gargalo é o Ollama (serializa na GPU), e o
trabalho é I/O-bound (HTTP + Postgres). Threads evitam o custo de serializar
chunks entre processos e mantêm um só pool de conexões. Medido no Temporal Wolf:
2 workers = 1.67x; 3-4 workers não melhoram (contenção na GPU).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")

# Número de workers default. 2 é o ponto ótimo medido: o Ollama serializa
# requisições na GPU, então acima disso só há contenção, não throughput.
DEFAULT_WORKERS = 2


class ProgressTracker:
    """Contador de progresso global, thread-safe, com pesos por item.

    Exemplo (4 itens com pesos desiguais):
        tracker = ProgressTracker([1.0, 3.0, 1.0, 1.0])
        tracker.advance(0)        # item 0 concluído  -> 1/6
        tracker.set_fraction(1, .5)  # metade do item 1 -> 1 + 1.5 = 2.5/6
        tracker.snapshot()        # 0.4166...
    """

    def __init__(self, weights: Iterable[float] | int):
        if isinstance(weights, int):
            weights = [1.0] * weights
        self._weights: list[float] = [float(w) for w in weights]
        self._done: list[float] = [0.0] * len(self._weights)
        self._total = sum(self._weights) or 1.0
        self._lock = threading.Lock()

    def set_fraction(self, index: int, fraction: float) -> None:
        """Registra que o item ``index`` está ``fraction`` (0.0-1.0) concluído."""
        fraction = max(0.0, min(1.0, float(fraction)))
        with self._lock:
            if 0 <= index < len(self._weights):
                self._done[index] = self._weights[index] * fraction

    def advance(self, index: int) -> None:
        """Marca o item ``index`` como 100% concluído."""
        with self._lock:
            if 0 <= index < len(self._weights):
                self._done[index] = self._weights[index]

    def snapshot(self) -> float:
        """Progresso global normalizado (0.0 -> 1.0)."""
        with self._lock:
            return min(sum(self._done) / self._total, 1.0)

    @property
    def total_items(self) -> int:
        return len(self._weights)


def run_parallel(
    items: Sequence[T],
    worker: Callable[[int, T, Callable[[float], None]], R],
    *,
    workers: int = DEFAULT_WORKERS,
    on_progress: Callable[[float], None] | None = None,
    on_result: Callable[[int, T, R | None, BaseException | None], None] | None = None,
    weights: Sequence[float] | None = None,
) -> list[R | None]:
    """Aplica ``worker`` a cada item, com ``workers`` threads, reportando progresso.

    O MESMO caminho serve ao caso sequencial e ao paralelo: com ``workers=1`` a
    execução é serial e o comportamento é idêntico ao de um laço simples. É isso
    que permite à UI ter uma única barra para upload único e para lote.

    Args:
        items: sequência de trabalho.
        worker: ``worker(index, item, set_fraction)``. Deve chamar ``set_fraction``
            com valores 0.0-1.0 para reportar progresso parcial do próprio item.
        workers: número de threads. Valores > número de itens são reduzidos.
        on_progress: callback chamado (fora do lock) a cada mudança de progresso,
            recebendo o progresso global 0.0-1.0.
        on_result: callback por item concluído, com ``(index, item, result, error)``.
            Um erro num item NÃO interrompe os demais.
        weights: peso relativo de cada item. Default: todos iguais.

    Returns:
        Lista de resultados na ordem dos itens; ``None`` onde o worker falhou.
    """
    if not items:
        if on_progress is not None:
            on_progress(1.0)
        return []

    if weights is None:
        weights = [1.0] * len(items)
    tracker = ProgressTracker(list(weights))

    def _report() -> None:
        if on_progress is not None:
            on_progress(tracker.snapshot())

    _report()  # progresso inicial (0.0) para a UI desenhar a barra já no começo

    results: list[R | None] = [None] * len(items)

    def _run_one(index: int, item: T) -> None:
        result: R | None = None
        error: BaseException | None = None
        try:
            result = worker(index, item, lambda f, i=index: _advance(i, f))
        except BaseException as exc:  # noqa: BLE001 — erro de um item não derruba o lote
            error = exc
        finally:
            tracker.advance(index)

        results[index] = result
        if on_result is not None:
            try:
                on_result(index, item, result, error)
            except Exception:  # callback da UI nunca deve derrubar o lote
                pass
        _report()

    def _advance(index: int, fraction: float) -> None:
        tracker.set_fraction(index, fraction)
        _report()

    effective_workers = max(1, min(workers, len(items)))
    if effective_workers == 1:
        # Caminho serial explícito: sem pool, comportamento idêntico ao laço simples.
        for index, item in enumerate(items):
            _run_one(index, item)
    else:
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = [pool.submit(_run_one, i, item) for i, item in enumerate(items)]
            for future in as_completed(futures):
                future.result()  # propaga apenas erros do próprio executor

    return results
