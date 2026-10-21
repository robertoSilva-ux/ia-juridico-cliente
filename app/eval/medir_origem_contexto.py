"""Mede de QUAIS DOCUMENTOS vem o contexto recuperado (P2-32).

O achado de 2026-10-20: o Decreto 3.048 tem 1.716 dos 2.141 fragmentos (80 %)
da base e ocupava a maior parte do top-15 em perguntas sobre a Lei 8.080. A
causa não é corpus ruim — é ranking: o tamanho relativo do documento decide
quem aparece, e o contexto de MAX_CONTEXT_CHARS é consumido por uma norma só.

Este medidor responde três perguntas, por item do mini-quiz:

  1. qual é o caminho de recuperação de fato (dispositivo/keyword/semântico)?
  2. quais documentos ocupam o top-K, em que ordem, e quantos chars cada um
     leva para o prompt (build_context)?
  3. aceite do cartão: os fragmentos da norma da pergunta estão entre os
     3 primeiros do contexto?

Uso (com `.env.dev` carregado, da raiz do repo):

    .venv/bin/python app/eval/medir_origem_contexto.py --rotulo antes
    .venv/bin/python app/eval/medir_origem_contexto.py --rotulo depois --hyde

`--hyde` liga o caminho completo (HyDE + RRF, com o LLM carregado); sem ele o
medidor usa só semântico+MMR, que é o que `retrieve_context` faz quando não há
LLM disponível. O resultado vai para `resultado_origem_<rotulo>.json`.
"""
import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

logging.disable(logging.INFO)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # app/

from agent import (  # noqa: E402
    EMBEDDINGS,
    _semantic_search,
    _semantic_with_rerank,
    ensure_llm,
    retrieve_context,
)
from config import (  # noqa: E402
    MAX_CHUNKS_PER_DOC,
    MAX_CONTEXT_CHARS,
    NORM_SCOPE_ENABLED,
    RERANK_ENABLED,
    TOP_K,
)
from ranking import _source_label, build_context  # noqa: E402

AQUI = Path(__file__).resolve().parent
QUIZ = json.loads((AQUI / "quiz_dev_lei8080.json").read_text())["questions"]

#: Norma que a pergunta pede. d1..d6 são todas sobre a Lei 8.080; d7 é
#: pergunta-armadilha (a resposta esperada é a recusa), então não tem norma.
NORMA_ESPERADA = {"d1": "8080", "d2": "8080", "d3": "8080",
                  "d4": "8080", "d5": "8080", "d6": "8080"}

#: Perguntas que NOMEIAM a norma sem citar artigo (ou que não citam artigo nem
#: norma). Existem porque o mini-quiz sozinho NÃO mede a dominância: cinco dos
#: seis itens citam "art. N da Lei 8.080" e caem na busca por metadados (R-15),
#: que já é escopada por norma — passariam o critério sem que nada fosse
#: consertado. Aqui o caminho é o semântico, que é onde o tamanho do documento
#: decide o resultado.
PROBES = [
    ("p1", "Quem exerce a direção do SUS no âmbito da União e nos Estados?", "8080"),
    ("p2", "O que é o Subsistema de Atenção à Saúde Indígena?", "8080"),
    ("p3", "Quais leis foram revogadas pela Lei 8.080?", "8080"),
    ("p4", "O que a Lei 8.080 diz sobre a participação da comunidade no SUS?", "8080"),
    ("p5", "Como a Lei 8.080 trata dos consórcios intermunicipais?", "8080"),
    ("p6", "O que diz a Lei 8.080 sobre a iniciativa privada na assistência à saúde?", "8080"),
    # Controle: pergunta sobre OUTRA norma grande (o decreto que domina a base).
    ("x1", "Qual o valor da cota do salário-família para o segurado com renda de até R$ 500?",
     "3048"),
]

USER_ID = 9  # mesmo usuário de dev dos outros medidores


def _chars_por_documento(docs):
    """Quanto de MAX_CONTEXT_CHARS cada documento consome no contexto final."""
    ctx = build_context(docs)
    usado = min(len(ctx), MAX_CONTEXT_CHARS)
    por_doc = Counter()
    for doc in docs:
        bloco = f"[DOC] {_source_label(doc)}\nArquivo: {doc.get('file_name', 'Sem nome')}\nConteúdo: {doc.get('content')}"
        # sem o número do [DOC n], que não muda o tamanho por documento
        por_doc[doc.get("file_name")] += len(bloco) + 2
    return ctx, usado, por_doc


def _analisa(pergunta_id, docs, norma):
    files = [d.get("file_name") for d in docs]
    numeros = [str(d.get("numero_doc") or "") for d in docs]
    posicoes = [i + 1 for i, num in enumerate(numeros) if norma and num == norma]
    ctx, usado, por_doc = _chars_por_documento(docs)
    return {
        "qid": pergunta_id,
        "norma_esperada": norma,
        "origem": sorted({d.get("origem") or "?" for d in docs}),
        "orfao_de_origem": sum(1 for d in docs if not d.get("origem")),
        "n_docs": len(docs),
        "files": files,
        "sequencia": [_source_label(d) for d in docs],
        "posicoes_da_norma": posicoes,
        "primeira_posicao": posicoes[0] if posicoes else None,
        "acima_de_3": bool(posicoes) and posicoes[0] <= 3,
        "lugares_da_norma": len(posicoes),
        "lugares_outros": len(docs) - len(posicoes),
        "chars_total": len(ctx),
        "chars_usados": usado,
        "chars_truncados": max(0, len(ctx) - MAX_CONTEXT_CHARS),
        "chars_por_documento": dict(por_doc.most_common()),
    }


def _base_atual() -> dict[str, int]:
    """Retrato da base no momento da medição (fragmentos por arquivo).

    Existe porque a base de dev é compartilhada: outra sessão pode reingerir ou
    limpar documentos no meio de uma medição, e sem este retrato "antes" e
    "depois" poderiam estar falando de bases diferentes.
    """
    from database import get_db_connection
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_name, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC")
            return dict(cur.fetchall())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotulo", default="atual", help="nome do cenário (antes/depois/…)")
    ap.add_argument("--hyde", action="store_true", help="liga o LLM para exercer o HyDE")
    ap.add_argument("--limit", type=int, default=TOP_K)
    args = ap.parse_args()

    if args.hyde:
        if not ensure_llm():
            sys.exit("LLM_MODEL não configurado: não dá para exercer o HyDE")

    base = _base_atual()
    print(f"base: {sum(base.values())} fragmentos em {len(base)} arquivos — " +
          " · ".join(f"{n} {a}" for a, n in base.items()))
    print(f"cenário: {args.rotulo} · TOP_K={args.limit} · RERANK={RERANK_ENABLED} · "
          f"MAX_CONTEXT_CHARS={MAX_CONTEXT_CHARS} · hyde={args.hyde}")
    print(f"{'id':<4} {'caminho':<24} {'1ª norma':>9} {'lugares':>8} {'chars':>7}  top-3 documentos")
    saida = {"rotulo": args.rotulo, "hyde": args.hyde, "limit": args.limit,
             "rerank": RERANK_ENABLED, "max_context_chars": MAX_CONTEXT_CHARS,
             "norm_scope": NORM_SCOPE_ENABLED, "max_chunks_per_doc": MAX_CHUNKS_PER_DOC,
             "base": base, "itens": []}

    casos = [(q["id"], q["question"], NORMA_ESPERADA.get(q["id"]), "quiz") for q in QUIZ]
    casos += [(pid, pergunta, norma, "probe") for pid, pergunta, norma in PROBES]

    for pergunta_id, pergunta, norma, grupo in casos:
        emb = EMBEDDINGS.embed_query(pergunta)
        # (a) o caminho real da aplicação
        real = retrieve_context(pergunta, user_id=USER_ID, limit=args.limit)
        # (b) semântico bruto (1ª etapa, sem MMR) — para atribuir a dominância
        bruto = _semantic_search(emb, USER_ID, args.limit, include_embedding=False)
        # (c) semântico + MMR (é o caminho sem metadados)
        mmr = _semantic_with_rerank(emb, USER_ID, args.limit, query=pergunta)
        for d in mmr:
            d.pop("embedding", None)

        registro = {
            "qid": pergunta_id,
            "grupo": grupo,
            "pergunta": pergunta,
            "real": _analisa(pergunta_id, real, norma),
            "semantico_bruto": _analisa(pergunta_id, bruto, norma),
            "semantico_mmr": _analisa(pergunta_id, mmr, norma),
        }
        saida["itens"].append(registro)
        r = registro["real"]
        caminho = "+".join(r["origem"]) + ("+sem" if r["orfao_de_origem"] else "")
        lugares = f"{r['lugares_da_norma']}/{r['n_docs']}"
        print(f"{pergunta_id:<4} {caminho:<24} {str(r['primeira_posicao']):>9} "
              f"{lugares:>8} {r['chars_usados']:>7}  "
              f"{', '.join(f.split('.')[0][:22] for f in r['files'][:3])}")

    for grupo, chave in (("quiz", "real"), ("probe", "real"), ("probe", "semantico_mmr")):
        itens = [i for i in saida["itens"] if i["grupo"] == grupo and i[chave]["norma_esperada"]]
        if not itens:
            continue
        ok = sum(1 for i in itens if i[chave]["acima_de_3"])
        lugares = sum(i[chave]["lugares_da_norma"] for i in itens)
        total = sum(i[chave]["n_docs"] for i in itens)
        fora = [f"{i['qid']}({i[chave]['primeira_posicao']})" for i in itens
                if not i[chave]["acima_de_3"]]
        print(f"\n[{grupo} · {chave}] norma da pergunta entre os 3 primeiros: "
              f"{ok}/{len(itens)} {('— fora: ' + ', '.join(fora)) if fora else ''}")
        print(f"[{grupo} · {chave}] lugares da norma da pergunta no top-{args.limit}: "
              f"{lugares}/{total}")

    legitimos = [i for i in saida["itens"] if i["real"]["norma_esperada"]]
    ocupados = Counter()
    for i in legitimos:
        for arq, n in i["real"]["chars_por_documento"].items():
            ocupados[arq] += n
    soma = sum(ocupados.values()) or 1
    print("\nchars de contexto por documento: " +
          " · ".join(f"{arq} {100*n/soma:.0f}%" for arq, n in ocupados.most_common()))
    truncados = [i["real"]["qid"] for i in legitimos if i["real"]["chars_truncados"]]
    print(f"contexto truncado em MAX_CONTEXT_CHARS: {truncados or 'nenhuma pergunta'}")

    destino = AQUI / f"resultado_origem_{args.rotulo}.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=1))
    print(f"gravado em {destino}")


if __name__ == "__main__":
    main()
