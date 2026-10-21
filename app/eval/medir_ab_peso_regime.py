"""A/B do peso por regime nas perguntas que ATIVAM o perfil (RGPS/RPPS).

O A/B anterior usou o mini-quiz, que é todo sobre a Lei 8.080 — e ali o perfil de regime
é vazio (`{'preferred': [], 'excluded': []}`), então desligar o peso não podia mudar
nada. Testar o boost só onde ele não atua não prova nada: aqui vão perguntas de RGPS
(que fazem `_infer_regime_profile` preferir 3.048/8.213) e de RPPS (EC 103).

Métrica dupla: a resposta é entregue (ok/parcial) e ela cita a norma esperada.
"""
import json
import logging
import re
import sys
import time
from pathlib import Path

logging.disable(logging.INFO)
RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "app"))

import agent  # noqa: E402
import regime  # noqa: E402

# (id, pergunta, regex da norma que a resposta deve citar)
CASOS = [
    ("rgps-dependentes", "Quais são os dependentes do segurado para fins de pensão por morte?",
     r"3\.?048|8\.?213"),
    ("rgps-salario-familia", "Qual o valor da cota do salário-família por dependente?",
     r"3\.?048|8\.?213"),
    ("rgps-carencia", "Como é contada a carência para a aposentadoria por tempo de contribuição?",
     r"3\.?048|8\.?213"),
    ("rpps-idade", "Qual a idade mínima para aposentadoria voluntária do servidor público federal?",
     r"103|Emenda"),
]
ITERACOES = 3
SAIDA = Path(__file__).resolve().parent / "resultado_ab_peso_regime_rgps.json"
ORIGINAL = agent._apply_regime_boost


def rodar(rotulo, com_boost):
    if not com_boost:
        agent._apply_regime_boost = lambda query, docs: docs
    try:
        print(f"\n=== {rotulo} ===")
        print("  perfis inferidos: " + ", ".join(
            f"{qid}={regime._infer_regime_profile(q)['preferred'] or 'vazio'}" for qid, q, _ in CASOS))
        saida = []
        for qid, pergunta, padrao in CASOS:
            entregues, citou, tempos = 0, 0, []
            for _ in range(ITERACOES):
                inicio = time.time()
                r = agent.get_response(pergunta)
                tempos.append(time.time() - inicio)
                status = r.get("status")
                if status in ("ok", "parcial"):
                    entregues += 1
                    if re.search(padrao, r.get("response") or r.get("answer") or ""):
                        citou += 1
            saida.append({"qid": qid, "entregues": entregues, "citou_norma": citou,
                          "tempos": [round(t, 1) for t in tempos]})
            print(f"  {qid:22} entregues {entregues}/{ITERACOES} | cita a norma {citou}/{ITERACOES} "
                  f"| tempos {[round(t, 1) for t in tempos]}")
        total = ITERACOES * len(CASOS)
        print(f"  TOTAL entregues {sum(x['entregues'] for x in saida)}/{total} | "
              f"citou norma {sum(x['citou_norma'] for x in saida)}/{total}")
        return {"rotulo": rotulo, "com_boost": com_boost, "casos": saida,
                "entregues": sum(x["entregues"] for x in saida),
                "citou_norma": sum(x["citou_norma"] for x in saida), "total": total}
    finally:
        agent._apply_regime_boost = ORIGINAL


com = rodar("COM peso por regime", True)
sem = rodar("SEM peso por regime", False)

print("\n=== comparacao ===")
print(f"  com boost: entregues {com['entregues']}/{com['total']} | cita norma {com['citou_norma']}/{com['total']}")
print(f"  sem boost: entregues {sem['entregues']}/{sem['total']} | cita norma {sem['citou_norma']}/{sem['total']}")
for a, b in zip(com["casos"], sem["casos"], strict=True):
    marca = "" if (a["entregues"], a["citou_norma"]) == (b["entregues"], b["citou_norma"]) else "  <<< DIFERENTE"
    print(f"  {a['qid']:22} com {a['entregues']}/{ITERACOES} cita {a['citou_norma']} | "
          f"sem {b['entregues']}/{ITERACOES} cita {b['citou_norma']}{marca}")

SAIDA.write_text(json.dumps({"com": com, "sem": sem}, ensure_ascii=False, indent=1))
print(f"\ngravado em {SAIDA}")
