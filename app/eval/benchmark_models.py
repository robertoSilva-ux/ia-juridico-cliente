#!/usr/bin/env python3
"""Bancada noturna: N iterações do quiz com tempo medido por resposta.

Variáveis de ambiente:
  BENCH_MODEL  - nome do modelo Ollama (obrigatório)
  BENCH_NUM_CTX - contexto (0 = default do Modelfile)
  BENCH_ITERS  - nº de iterações (default 20)
  BENCH_QUIZ   - caminho do quiz (default quiz_loop_q6.json)
  BENCH_OUT    - caminho do relatório JSON de saída (obrigatório)

Grava o JSON incrementalmente a cada resposta, para sobreviver a crash
no meio da noite sem perder o que já rodou.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_DIR))

MODEL = os.environ["BENCH_MODEL"]
NUM_CTX = int(os.environ.get("BENCH_NUM_CTX", "0"))
ITERS = int(os.environ.get("BENCH_ITERS", "20"))
QUIZ = os.environ.get("BENCH_QUIZ", str(SCRIPT_DIR / "relatorios" / "quiz_loop_q6.json"))
OUT = os.environ["BENCH_OUT"]

# O config.py le LLM_NUM_CTX no import do agent — wire ANTES do import.
if NUM_CTX > 0:
    os.environ["LLM_NUM_CTX"] = str(NUM_CTX)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

from agent import get_response  # noqa: E402  (import depois do logging)


def keyword_recall(answer: str, keywords: list) -> dict:
    low = answer.lower()
    hits = [k for k in keywords if k.lower() in low]
    return {"hits": hits, "hit_count": len(hits), "total": len(keywords)}


def main():
    with open(QUIZ, encoding="utf-8") as f:
        quiz = json.load(f)
    questions = quiz["questions"] if isinstance(quiz, dict) else quiz

    results = {
        "model": MODEL,
        "num_ctx": NUM_CTX if NUM_CTX > 0 else "default",
        "iters": ITERS,
        "quiz": QUIZ,
        "started_at": datetime.now().isoformat(),
        "runs": [],
    }

    def save():
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)

    done = 0
    t_config_start = time.perf_counter()
    for i in range(1, ITERS + 1):
        for q in questions:
            t0 = time.perf_counter()
            err = None
            try:
                resp = get_response(q["question"])
            except Exception as e:  # noqa: BLE001 - registrar e continuar
                resp, err = {}, f"{type(e).__name__}: {e}"
            dt = round(time.perf_counter() - t0, 2)

            answer = resp.get("answer", "")
            fc = resp.get("fact_check", {}) or {}
            sources = resp.get("sources", []) or []
            distances = [s.get("distance") for s in sources if s.get("distance") is not None]
            results["runs"].append({
                "iter": i,
                "qid": q["id"],
                "time_s": dt,
                "error": err,
                "answer": answer,
                "answer_chars": len(answer),
                "grounded": fc.get("all_grounded"),
                "supported": fc.get("supported"),
                "partial": fc.get("partial"),
                "no_support": fc.get("no_support"),
                "keyword_recall": keyword_recall(answer, q.get("expected_keywords", [])),
                "num_sources": len(sources),
                "avg_distance": round(sum(distances) / len(distances), 4) if distances else None,
            })
            done += 1
            save()
            print(f"[{MODEL} ctx={NUM_CTX or 'def'}] it={i}/{ITERS} {q['id']} "
                  f"{dt}s grounded={fc.get('all_grounded')} err={bool(err)}", flush=True)
    results["wall_time_s"] = round(time.perf_counter() - t_config_start, 1)
    results["finished_at"] = datetime.now().isoformat()
    save()
    print(f"DONE {MODEL} ctx={NUM_CTX or 'def'}: {done} respostas em {results['wall_time_s']}s", flush=True)


if __name__ == "__main__":
    main()
