#!/usr/bin/env python
"""Traz o corpus OFICIAL do Planalto para a base e reingere (P2-30).

Por que existe: o material indexado na base de dev é uma apostila ("esquematizada"), onde
o número da lei aparece em um fragmento e o ano em outro — o modelo adivinha a identidade
da norma e o fact-check não tem o que verificar. No texto do Planalto o cabeçalho
("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990") traz o par número+ano, e a identidade do
documento (R-9) passa a vir do conteúdo.

Três etapas, separadas de propósito (a conversão é auditável e o download é o único passo
que depende da rede):

    # 1. baixa o HTML oficial (grava .htm e manifesto com sha256 + data de acesso)
    .venv/bin/python scripts/corpus_planalto.py --baixar

    # 2. converte HTML -> texto limpo (grava .txt ao lado do .htm)
    .venv/bin/python scripts/corpus_planalto.py --converter

    # 3. ingere na base (precisa de DATABASE_URL/OLLAMA_BASE_URL — carregue o .env.dev)
    set -a; . ./.env.dev; set +a
    .venv/bin/python scripts/corpus_planalto.py --ingerir

Sem flag, faz as três. `--normas l8080,lcp142` restringe o escopo, o que é útil para medir
o efeito de uma norma antes de pagar o custo de embedding do corpus inteiro.

Os arquivos ficam em `data/corpus-planalto/` (ignorado pelo git): são dados, não código.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import socket
import sys
import time
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "data", "corpus-planalto")
MANIFESTO = os.path.join(DESTINO, "manifesto.json")

#: Fontes oficiais. `escopo` diz o que a norma cobre, para o relatório da ingestão.
NORMAS = {
    "l8080": {
        "url": "https://www.planalto.gov.br/ccivil_03/leis/l8080.htm",
        "titulo": "Lei nº 8.080/1990 — Lei Orgânica da Saúde",
    },
    "lcp142": {
        "url": "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp142.htm",
        "titulo": "Lei Complementar nº 142/2013 — aposentadoria da pessoa com deficiência",
    },
    "emc103": {
        "url": "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc103.htm",
        "titulo": "Emenda Constitucional nº 103/2019 — reforma da previdência",
    },
    "d3048": {
        "url": "https://www.planalto.gov.br/ccivil_03/decreto/d3048.htm",
        "titulo": "Decreto nº 3.048/1999 — Regulamento da Previdência Social",
    },
}

#: Tags que delimitam bloco. O chunker jurídico depende de dispositivo vir em parágrafo
#: próprio; texto corrido juntaria dois artigos numa linha e a fronteira se perderia.
_TAGS_DE_BLOCO = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                  "table", "center"}
_TAGS_IGNORADAS = {"script", "style", "head"}


class _ExtratorDeBlocos(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self._pular = 0

    def handle_starttag(self, tag, attrs):
        if tag in _TAGS_IGNORADAS:
            self._pular += 1
        elif tag in _TAGS_DE_BLOCO:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in _TAGS_IGNORADAS and self._pular:
            self._pular -= 1
        elif tag in _TAGS_DE_BLOCO:
            self.partes.append("\n")

    def handle_data(self, data):
        if not self._pular:
            self.partes.append(data)


def _decodificar(bruto: bytes) -> str:
    """Texto do HTML no charset declarado. O Planalto serve ISO-8859-1 na maior parte."""
    marca = re.search(rb'charset=["\']?([\w-]+)', bruto[:2000], re.I)
    charset = marca.group(1).decode("ascii", "ignore").lower() if marca else "latin-1"
    if charset in {"iso-8859-1", "latin1", "windows-1252"}:
        charset = "latin-1"
    try:
        return bruto.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return bruto.decode("latin-1")


def html_para_texto(bruto: bytes) -> str:
    """HTML do Planalto -> texto com um parágrafo por bloco, sem tags nem entidades."""
    parser = _ExtratorDeBlocos()
    parser.feed(_decodificar(bruto))
    linhas = []
    for linha in "".join(parser.partes).split("\n"):
        linha = re.sub(r"[ \t\u00a0]+", " ", html.unescape(linha)).strip()
        if linha:
            linhas.append(linha)
    return "\n\n".join(linhas).strip() + "\n"


def baixar(slugs):
    os.makedirs(DESTINO, exist_ok=True)
    manifesto = {}
    if os.path.exists(MANIFESTO):
        with open(MANIFESTO, encoding="utf-8") as arquivo:
            manifesto = json.load(arquivo)
    for slug in slugs:
        norma = NORMAS[slug]
        destino = os.path.join(DESTINO, f"{slug}.htm")
        requisicao = urllib.request.Request(
            norma["url"], headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
        with urllib.request.urlopen(requisicao, timeout=120) as resposta:
            bruto = resposta.read()
        with open(destino, "wb") as arquivo:
            arquivo.write(bruto)
        manifesto[slug] = {
            "url": norma["url"],
            "titulo": norma["titulo"],
            "acessado_em": datetime.now(UTC).isoformat(timespec="seconds"),
            "bytes": len(bruto),
            "sha256": hashlib.sha256(bruto).hexdigest(),
        }
        print(f"  baixado {slug}: {len(bruto)} bytes")
    with open(MANIFESTO, "w", encoding="utf-8") as arquivo:
        json.dump(manifesto, arquivo, ensure_ascii=False, indent=2, sort_keys=True)


def converter(slugs):
    for slug in slugs:
        origem = os.path.join(DESTINO, f"{slug}.htm")
        if not os.path.exists(origem):
            print(f"  {slug}: sem .htm — rode --baixar primeiro", file=sys.stderr)
            continue
        with open(origem, "rb") as arquivo:
            texto = html_para_texto(arquivo.read())
        destino = os.path.join(DESTINO, f"{slug}.txt")
        with open(destino, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto)
        dispositivos = len(re.findall(r"(?m)^\s*Art(?:\.|igo)?\s*\d+", texto))
        print(f"  convertido {slug}: {len(texto)} chars, {dispositivos} dispositivos")


def ingerir(slugs, owner_id=None, scope="global"):
    sys.path.insert(0, os.path.join(RAIZ, "app"))
    from config import EMBEDDING_MODEL, OLLAMA_BASE_URL
    from embeddings import NomicOllamaEmbeddings
    from ingest import ingest_document

    embeddings = NomicOllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_BASE_URL)
    print(f"  embeddings: {EMBEDDING_MODEL} em {OLLAMA_BASE_URL}; escopo={scope} dono={owner_id}")
    for slug in slugs:
        caminho = os.path.join(DESTINO, f"{slug}.txt")
        if not os.path.exists(caminho):
            print(f"  {slug}: sem .txt — rode --converter primeiro", file=sys.stderr)
            continue
        inicio = time.time()
        indexados = ingest_document(caminho, embeddings, f"{slug}.txt",
                                    owner_id=owner_id, scope=scope)
        print(f"  ingerido {slug}: {indexados} fragmentos em {time.time() - inicio:.1f}s")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--normas", default=",".join(NORMAS),
                        help="slugs separados por vírgula (padrão: todas)")
    parser.add_argument("--baixar", action="store_true")
    parser.add_argument("--converter", action="store_true")
    parser.add_argument("--ingerir", action="store_true")
    parser.add_argument("--owner-id", type=int, default=None)
    parser.add_argument("--scope", default="global", choices=["global", "private"])
    args = parser.parse_args(argv)

    slugs = [s.strip() for s in args.normas.split(",") if s.strip()]
    desconhecidas = [s for s in slugs if s not in NORMAS]
    if desconhecidas:
        parser.error(f"norma desconhecida: {', '.join(desconhecidas)}")

    etapas = (args.baixar, args.converter, args.ingerir)
    if not any(etapas):
        args.baixar = args.converter = args.ingerir = True

    if args.baixar:
        print("baixando do Planalto:")
        baixar(slugs)
    if args.converter:
        print("convertendo HTML -> texto:")
        converter(slugs)
    if args.ingerir:
        print("ingerindo:")
        ingerir(slugs, owner_id=args.owner_id, scope=args.scope)
    return 0


if __name__ == "__main__":
    socket.setdefaulttimeout(120)
    sys.exit(main())
