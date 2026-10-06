#!/usr/bin/env python3
"""Avaliador reproduzível do RAG jurídico (Legaliz.ai).

Roda o questionário (app/eval/quiz.json) contra o pipeline real de geração
(`get_response`) e grava um relatório JSON com, para cada pergunta:
  - a resposta gerada;
  - as fontes recuperadas (file_name + distância vetorial);
  - métricas objetivas: nº de fontes, distância média, recall de keywords.

Comparar o relatório de ANTES vs DEPOIS de uma mudança (ex.: recuperação
assimétrica, HyDE, MMR) mostra o impacto real, em vez de achismo.

Uso (de dentro do container app, que enxerga `db` e `ollama`):
  python3 eval/run_eval.py [--out relatorio.json] [--quiz eval/quiz.json]
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_DIR))

from agent import get_response  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval")


def load_quiz(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def keyword_recall(answer: str, keywords: list) -> dict:
    """Conta quantas keywords esperadas aparecem (case-insensitive) na resposta."""
    low = answer.lower()
    hits = [k for k in keywords if k.lower() in low]
    return {"hits": hits, "hit_count": len(hits), "total": len(keywords)}


# Números que, em contexto de aposentadoria/prazos, são típicos de requisito
# inventado (anos de contribuição/idade, prazos). Sinal de possível persistência
# de alucinação mesmo quando o modelo também usa um marcador de recusa.
_NUM_PATTERN = re.compile(r"\b(\d{1,3})\s*(anos?|dias?|meses?)\b", re.IGNORECASE)

# Citação de dispositivo (art. N, §N, inciso N) numa pergunta cuja resposta a
# base NÃO contém: é afirmação desancorada, mesmo sem número de prazo.
_DISPOSITIVO_PATTERN = re.compile(
    r"\b(art(?:igo)?\.?\s*\d+|§\s*\d+|inciso\s+[IVXLCDM]+)", re.IGNORECASE
)


def evaluate_refusal(answer: str, markers: list) -> dict:
    """Avalia uma pergunta cuja resposta correta é RECUSAR (base não contém).

    Retorna:
      - 'ok_refusal'    : contém marcador de recusa e nenhuma afirmação concreta
      - 'hallucination' : afirma números/dispositivos sem marcador de recusa
      - 'ambiguous'     : mistura recusa com afirmações concretas
    """
    low = answer.lower()
    marker_hits = [m for m in markers if m.lower() in low]
    num_hits = _NUM_PATTERN.findall(answer)
    dispositivo_hits = _DISPOSITIVO_PATTERN.findall(answer)
    concrete = [" ".join(n) for n in num_hits] + list(dispositivo_hits)

    if marker_hits and not concrete:
        verdict = "ok_refusal"
    elif concrete and not marker_hits:
        verdict = "hallucination"
    else:
        verdict = "ambiguous"

    return {
        "verdict": verdict,
        "refusal_markers_hit": marker_hits,
        "numeric_claims": [" ".join(n) for n in num_hits],
        "dispositivo_claims": list(dispositivo_hits),
    }


def run(quiz_path: Path, out_path: Path):
    quiz = load_quiz(quiz_path)
    results = {
        "generated_at": datetime.now().isoformat(),
        "quiz": str(quiz_path),
        "questions": [],
    }

    for q in quiz["questions"]:
        qid = q["id"]
        logger.info(f"Rodando {qid}: {q['question']}")
        print(f"\n=== [{qid}] {q['question']} ===")

        resp = get_response(q["question"])

        answer = resp.get("answer", "")
        sources = resp.get("sources", [])
        fact_check = resp.get("fact_check", {})

        # Métricas de recuperação
        distances = [s.get("distance") for s in sources if s.get("distance") is not None]
        avg_distance = round(sum(distances) / len(distances), 4) if distances else None
        files = [s.get("file_name") for s in sources if s.get("file_name")]

        recall = keyword_recall(answer, q.get("expected_keywords", []))

        # Recuperação isolada (hit@k): dos arquivos esperados, quantos apareceram
        # entre as fontes recuperadas? Mede o RETRIEVER separado da geração.
        expected_files = [f for f in q.get("expected_files", []) if f]
        source_hits = []
        if expected_files:
            files_low = {f.lower(): f for f in files}
            source_hits = [f for f in expected_files
                           if any(f.lower() in fl or fl in f.lower() for fl in files_low)]
        source_hit = {
            "expected": expected_files,
            "hits": source_hits,
            "hit_count": len(source_hits),
            "total": len(expected_files),
            "recall": round(len(source_hits) / len(expected_files), 3) if expected_files else None,
        }

        # Recuperação GRANULAR (hit por artigo): um documento pode ter centenas
        # de chunks; o arquivo esperado aparecer NÃO garante que o ARTIGO
        # perguntado tenha vindo. Sem esta métrica, `source_hit` dá 1/1 com o
        # artigo errado no contexto (foi o que mascarou as falhas de q6/q7/q9).
        # `expected_article` no quiz liga a checagem; o campo `artigo` vem das
        # sources (agent.get_response passa a expor a coluna estruturada).
        expected_article = q.get("expected_article")
        article_hit = None
        if expected_article is not None:
            artigos = {str(s.get("artigo")) for s in sources if s.get("artigo") is not None}
            esperado = str(expected_article)
            article_hit = {
                "expected": esperado,
                "hit": esperado in artigos,
                "artigos_recuperados": sorted(artigos, key=lambda a: int(a) if a.isdigit() else 0),
            }

        expectation = q.get("expectation", "answer")
        entry = {
            "id": qid,
            "question": q["question"],
            "expectation": expectation,
            "answer": answer,
            "num_sources": len(sources),
            "avg_distance": avg_distance,
            "min_distance": (round(min(distances), 4) if distances else None),
            "source_files": files,
            "keyword_recall": recall,
            "source_hit": source_hit,
            "article_hit": article_hit,
            "fact_check": fact_check,
        }

        if expectation == "refuse":
            refusal = evaluate_refusal(answer, q.get("refusal_markers", []))
            entry["refusal_eval"] = refusal
            print(f"  -> [refuse] veredito={refusal['verdict']} | "
                  f"markers={len(refusal['refusal_markers_hit'])} | "
                  f"numeros={refusal['numeric_claims']} | "
                  f"dispositivos={refusal['dispositivo_claims']}")
        else:
            hit_txt = (f" | fonte esperada: {source_hit['hit_count']}/{source_hit['total']}"
                       if expected_files else "")
            art_txt = ""
            if article_hit is not None:
                art_txt = f" | ARTIGO {article_hit['expected']}: {'HIT' if article_hit['hit'] else 'MISS'}"
            print(f"  -> {len(sources)} fontes | dist média={avg_distance} | "
                  f"keywords={recall['hit_count']}/{recall['total']}{hit_txt}{art_txt}")

        results["questions"].append(entry)

        # Resumo no stdout
        print(f"     resposta: {answer[:160]}{'...' if len(answer) > 160 else ''}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nRelatório salvo em: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Avaliador RAG jurídico.")
    parser.add_argument("--out", type=str, default="relatorio_eval.json")
    parser.add_argument("--quiz", type=str, default="quiz.json")
    args = parser.parse_args()

    quiz_path = (SCRIPT_DIR / args.quiz) if not Path(args.quiz).is_absolute() else Path(args.quiz)
    out_path = (SCRIPT_DIR / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    if not quiz_path.exists():
        print(f"Questionário não encontrado: {quiz_path}", file=sys.stderr)
        sys.exit(1)

    run(quiz_path, out_path)


if __name__ == "__main__":
    main()
