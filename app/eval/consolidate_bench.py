#!/usr/bin/env python3
"""Consolida os relatórios bench_*.json da bancada noturna em um comparativo.

Roda no HOST (só lê JSON). Saída:
  app/eval/relatorios/relatorio_bancada_noturna.json
  app/eval/relatorios/relatorio_bancada_noturna.md
"""

import json
import re
import statistics as st
from pathlib import Path

REL = Path(__file__).resolve().parent / "relatorios"

# Idade correta p/ q6 (art. 83, Decreto 3.048/99): 14 anos. Confusores vistos:
# 21 (dependência p/ pensão, art. 16) e 18 (alucinação de conhecimento interno).
IDADE_CORRETA = 14
AGE_RE = re.compile(r"\b(\d{1,3})\s*anos?\b", re.IGNORECASE)
EXTENSO = {"quatorze": 14, "catorze": 14, "quatroze": 14, "dezoito": 18,
           "vinte e um": 21, "dezenove": 19, "dezessete": 17, "quinze": 15,
           "dezesseis": 16, "sessenta e cinco": 65, "cinquenta e cinco": 55}


def ages_in(text: str):
    found = [int(x) for x in AGE_RE.findall(text or "")]
    low = (text or "").lower()
    for w, v in EXTENSO.items():
        if w in low:
            found.append(v)
    return found


def pct(vals, p):
    s = sorted(vals)
    if not s:
        return None
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def summarize_runs(runs):
    ok = [r for r in runs if not r.get("error")]
    times = [r["time_s"] for r in ok]
    grounded = [r.get("grounded") for r in ok]
    kw = [(r.get("keyword_recall") or {}).get("hit_count", 0) for r in ok]
    ages_counter = {}
    refusals = 0
    correct = 0
    for r in ok:
        aa = set(ages_in(r.get("answer", "")))
        if not aa:
            refusals += 1
        if IDADE_CORRETA in aa:
            correct += 1
        for a in aa:
            ages_counter[a] = ages_counter.get(a, 0) + 1
    return {
        "n": len(runs),
        "errors": len(runs) - len(ok),
        "time_mean_s": round(st.mean(times), 1) if times else None,
        "time_median_s": round(st.median(times), 1) if times else None,
        "time_p95_s": pct(times, 95),
        "time_min_s": min(times) if times else None,
        "grounded_rate": round(sum(1 for x in grounded if x is True) / len(grounded), 3) if grounded else None,
        "kw_mean": round(st.mean(kw), 2) if kw else None,
        "q6_correct_rate": round(correct / len(ok), 3) if ok else None,
        "q6_ages_dist": dict(sorted(ages_counter.items(), key=lambda kv: -kv[1])),
        "q6_refusals": refusals,
        "answer_chars_mean": round(st.mean([r.get("answer_chars", 0) for r in ok])) if ok else None,
    }


def main():
    files = sorted(REL.glob("bench_*.json"))
    summary = {"generated_at": None, "configs": {}, "quizfull": {}}
    rows = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"skip {f.name}: {e}")
            continue
        tag = f.stem.replace("bench_", "")
        model, ctx = d.get("model"), d.get("num_ctx")
        runs = d.get("runs", [])
        if "quizfull" in tag:
            # quiz completo: agrupa por pergunta entre as repetições r1/r2/r3
            base = tag.rsplit("_r", 1)[0]
            for r in runs:
                summary["quizfull"].setdefault(base, {}).setdefault(r["qid"], []).append({
                    "time_s": r["time_s"], "kw": (r.get("keyword_recall") or {}).get("hit_count"),
                    "kw_total": (r.get("keyword_recall") or {}).get("total"),
                    "grounded": r.get("grounded"), "error": r.get("error"),
                })
            continue
        s = summarize_runs(runs)
        s.update({"model": model, "num_ctx": ctx, "file": f.name,
                  "wall_time_s": d.get("wall_time_s")})
        summary["configs"][tag] = s
        rows.append((tag, s))
        print(f"{tag}: med={s['time_median_s']}s p95={s['time_p95_s']}s "
              f"grounded={s['grounded_rate']} q6_ok={s['q6_correct_rate']} "
              f"idades={s['q6_ages_dist']}")

    # ranking: qualidade primeiro (q6_correct, grounded), depois velocidade
    rows.sort(key=lambda kv: (-(kv[1]["q6_correct_rate"] or 0),
                              -(kv[1]["grounded_rate"] or 0),
                              kv[1]["time_median_s"] or 9e9))

    lines = [
        "# Bancada noturna legaliz.ai — comparativo de modelos",
        "",
        "20 respostas da q6 (salário-família, gabarito: 14 anos) por configuração.",
        "Qualidade = taxa de acerto da idade + groundedness; velocidade = tempo por resposta.",
        "",
        "| config | modelo | ctx | n | erro | t med (s) | t p95 (s) | grounded | q6 correta | idades citadas |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for tag, s in rows:
        lines.append("| {tag} | {m} | {c} | {n} | {e} | {tm} | {p} | {g} | {q} | {a} |".format(
            tag=tag, m=(s["model"] or "").replace("|", "/"), c=s["num_ctx"], n=s["n"],
            e=s["errors"], tm=s["time_median_s"], p=s["time_p95_s"],
            g=s["grounded_rate"], q=s["q6_correct_rate"], a=s["q6_ages_dist"]))
    lines.append("")
    quizfull = summary.get("quizfull") or {}
    if quizfull:
        lines += ["## Quiz completo (6 perguntas) — runs repetidas", ""]
        for base, qs in sorted(quizfull.items()):
            lines.append(f"### {base}")
            lines.append("")
            lines.append("| qid | runs | t med (s) | kw por run | grounded |")
            lines.append("|---|---|---|---|---|")
            for qid, rs in sorted(qs.items()):
                times = [r["time_s"] for r in rs if not r.get("error")]
                med = round(st.median(times), 1) if times else "-"
                kws = "/".join(str(r.get("kw")) for r in rs)
                gr = sum(1 for r in rs if r.get("grounded") is True)
                lines.append(f"| {qid} | {len(rs)} | {med} | {kws} | {gr}/{len(rs)} |")
            lines.append("")

    (REL / "relatorio_bancada_noturna.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(REL / "relatorio_bancada_noturna.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\nOK -> relatorio_bancada_noturna.md/.json")


if __name__ == "__main__":
    main()
