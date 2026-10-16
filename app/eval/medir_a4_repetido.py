"""A4 medido com repetição: 3 iterações por pergunta cuja resposta está na base.

Uma passagem só mede o humor do modelo, não a taxa: o phi4-mini:3.8b recusa de
forma instável perguntas simples mesmo com o trecho no contexto. Aqui cada
pergunta legítima do mini-quiz roda N vezes e o resultado é a taxa de resposta.
"""
import json
import logging
import statistics
import sys
import time
from pathlib import Path

logging.disable(logging.INFO)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # app/
from agent import get_response  # noqa: E402

#: Mesmo diretório deste arquivo: o quiz e os resultados vivem junto do medidor.
SCRATCH = Path(__file__).resolve().parent
SAIDA = SCRATCH / "resultado_a4_rep.json"
ITERACOES = 3

quiz = json.loads((SCRATCH / "quiz_dev_lei8080.json").read_text())["questions"]
legit = [q for q in quiz if not any(k.startswith("não") for k in q.get("expected_keywords", []))]

runs = []
print(f"{'id':<4} {'respostas':<12} {'recusas':<9} {'parcial':<9} tempos")
for item in legit:
    respostas = recusas = parciais = 0
    tempos = []
    for i in range(ITERACOES):
        t0 = time.time()
        r = get_response(item["question"], [], user_id=9, user_email="dev@legaliz.local")
        dt = time.time() - t0
        tempos.append(round(dt, 1))
        runs.append({
            "qid": item["id"], "iter": i + 1, "status": r["status"], "motivo": r["motivo"],
            "suficiente": r.get("suficiente"), "time_s": round(dt, 1),
            "answer": r["answer"], "descartada": r.get("descartada"),
        })
        SAIDA.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
        if r["status"] == "ok":
            respostas += 1
        elif r["status"] == "recusada":
            recusas += 1
        elif r["status"] == "parcial":
            respostas += 1
            parciais += 1
    print(f"{item['id']:<4} {respostas}/{ITERACOES:<8} {recusas:<9} {parciais:<9} {tempos}")

print("\n=== resumo ===")
status = [r["status"] for r in runs]
print(f"respondidas (ok+parcial): {sum(1 for s in status if s in ('ok', 'parcial'))}/{len(runs)}")
print(f"recusadas: {sum(1 for s in status if s == 'recusada')}/{len(runs)}")
print(f"erros: {sum(1 for s in status if s == 'erro')}")
t = sorted(r["time_s"] for r in runs)
print(f"latência: mediana {statistics.median(t):.1f}s · p95 {t[min(len(t)-1, int(0.95*len(t)))]:.1f}s · máx {t[-1]:.1f}s")
