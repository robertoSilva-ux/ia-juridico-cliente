"""Mede a Fase 1 no banco real, com o modelo: o que o chat EXIBE em cada caso.

Critérios de aceite (docs/PLANO_REFINAMENTO_RAG.md, §1):
  A1 nenhuma resposta exibida com norma/dispositivo sem lastro
  A2 pergunta cuja resposta não está na base -> recusa, não resposta
  A4 pergunta legítima continua respondida (não viramos um recusador)
Grava cada resposta em resultado_fase1.json (append) e imprime a tabela.
"""
import json
import logging
import sys
import time
from pathlib import Path

logging.disable(logging.INFO)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # app/
from agent import get_response  # noqa: E402

#: Mesmo diretório deste arquivo: o quiz e os resultados vivem junto do medidor.
SCRATCH = Path(__file__).resolve().parent
SAIDA = SCRATCH / "resultado_portao.json"

quiz = json.loads((SCRATCH / "quiz_dev_lei8080.json").read_text())["questions"]
fora = [
    ("f1", "Qual o prazo de prescrição para a ação de usucapião extraordinária?"),
    ("f2", "Como funciona a rescisão indireta do contrato de trabalho?"),
    ("f3", "Qual o prazo para o consumidor reclamar de vício aparente do produto?"),
    ("f4", "Quais são as hipóteses de dispensa de licitação na nova Lei de Licitações?"),
    ("f5", "Como se calcula a pensão alimentícia entre ex-cônjuges?"),
    ("f6", "Qual a pena para o crime de peculato?"),
]

# A pergunta-armadilha do mini-quiz tem como resposta esperada a RECUSA ("não
# consta/não contém…"): é a d7. Ela entra na estatística como "não contém".
def _espera_recusa(item):
    return any(palavra.startswith("não") for palavra in item.get("expected_keywords", []))


casos = [(q["id"], q["question"], not _espera_recusa(q)) for q in quiz]
casos += [(i, t, False) for i, t in fora]
n_legitimas = sum(1 for _, _, d in casos if d)

runs = []
print(f"{'id':<4} {'esperado':<10} {'status':<10} {'motivo':<22} {'veredito-fc':<13} "
      f"{'t(s)':>6}  resposta/top")
for qid, pergunta, dentro in casos:
    t0 = time.time()
    r = get_response(pergunta, [], user_id=9, user_email="dev@legaliz.local")
    dt = time.time() - t0
    fc = r.get("fact_check") or {}
    registro = {
        "qid": qid, "esperado_contem": dentro, "pergunta": pergunta, "time_s": round(dt, 1),
        "status": r.get("status"), "motivo": r.get("motivo"), "suficiente": r.get("suficiente"),
        "veredito": fc.get("veredito"), "no_support": fc.get("no_support"),
        "partial": fc.get("partial"), "citadas": fc.get("citadas"),
        "answer": r.get("answer"), "descartada": r.get("descartada"),
        "fontes": len(r.get("sources") or []),
    }
    runs.append(registro)
    SAIDA.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    print(f"{qid:<4} {'contém' if dentro else 'NÃO contém':<10} {str(r.get('status')):<10} "
          f"{str(r.get('motivo'))[:20]:<22} {str(fc.get('veredito'))[:11]:<13} {dt:>6.1f}  "
          f"{(r.get('answer') or '')[:60].replace(chr(10), ' ')}")

print("\n=== resumo ===")
recusadas_fora = sum(1 for r in runs if not r["esperado_contem"] and r["status"] == "recusada")
respondidas_dentro = sum(1 for r in runs if r["esperado_contem"] and r["status"] in ("ok", "parcial"))
inventadas = sum(1 for r in runs if r["status"] in ("ok", "parcial") and r["no_support"])
nao_respondidas = [r["qid"] for r in runs if r["esperado_contem"] and r["status"] == "recusada"]
tempos = sorted(r["time_s"] for r in runs)
p95 = tempos[min(len(tempos) - 1, int(0.95 * len(tempos)))]
print(f"A2 recusa nas perguntas fora da base .... {recusadas_fora}/{len(runs) - n_legitimas}")
print(f"A4 legítimas respondidas ................ {respondidas_dentro}/{n_legitimas}  {nao_respondidas or ''}")
print(f"A1 exibidas com norma/dispositivo sem lastro . {inventadas}")
print(f"latência: mediana {tempos[len(tempos)//2]:.1f}s · p95 {p95:.1f}s · máx {tempos[-1]:.1f}s")
