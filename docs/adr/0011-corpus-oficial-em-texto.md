# ADR-0011 — O corpus oficial entra como texto, não como PDF sintético

- **Status:** aceito
- **Data:** 2026-10-20
- **Origem:** P2-30 do [`BACKLOG.md`](../BACKLOG.md) ("corpus precisa ser fonte oficial, não
  material didático"), que destravava o **R-16** e a Fase 3 do
  [`PLANO_REFINAMENTO_RAG.md`](../PLANO_REFINAMENTO_RAG.md)

## Contexto

A base de dev indexava uma **apostila** ("LEI-8080-ESQUEMATIZADA1.pdf"): o número da lei aparece
em um fragmento e o ano em outro, e cada fragmento carrega o rodapé do cursinho. O R-9 já lia a
identidade do documento do conteúdo, mas o material não dá o par número+ano de forma
verificável — e o R-16 (portão relativo) não tinha corpus em que calibrar.

O texto oficial está disponível no Planalto, em **HTML** (`planalto.gov.br/ccivil_03/...`), e a
ingestão só sabia ler **PDF** (`PyPDFLoader` → uma página por `Document`). Três caminhos
possíveis:

1. **Gerar um PDF** a partir do HTML e reingerir pelo caminho atual — zero mudança de código.
2. **Colocar um parser de HTML na app** — a ingestão passaria a ter dois extratores.
3. **Converter fora da app e aceitar texto plano** — a conversão vira script versionado e a
   ingestão ganha um segundo formato de entrada, sem parser de HTML.

## Decisão

**Opção 3.** `scripts/corpus_planalto.py` baixa o HTML oficial, grava manifesto com `sha256` e
data de acesso, converte para `.txt` (um parágrafo por bloco, `html.parser` da stdlib — sem
dependência nova) e, opcionalmente, ingere. `ingest.extrair_paginas` aceita `.txt` e pagina o
texto **sinteticamente**, a cada ~4.000 caracteres, sempre em fronteira de linha em branco.

Três razões para não gerar PDF:

- PDF sintético é etapa frágil: quem gera, com que fonte, com que hifenização? O texto oficial
  já vem em parágrafos; passá-lo por um gerador de PDF para depois extrair de novo é
  retrabalho que pode introduzir exatamente o ruído que o R-10/R-11 limpam.
- O cliente vai reingerir o Planalto periodicamente: um script com manifesto (`url`, `sha256`,
  data) é auditável; um PDF gerado à mão não é.
- O PDF *real* do Planalto (quando existe) tem cabeçalho repetido por página, mas a versão
  canônica publicada é o HTML — é dele que sai o texto consolidado.

**A "página" de um `.txt` é convenção declarada**, não paginação inventada: o pipeline é por
página (limpeza de ruído comparando páginas, metadado `pagina`, estado do dispositivo entre
páginas) e precisa de uma unidade estável. A limpeza de cabeçalho/rodapé repetido **não** roda
em `.txt` — ela existe para apostila paginada e apagaria linha legítima que se repete entre
páginas sintéticas.

## Consequências

- **Medido na base de dev (2026-10-20)**, com `--ingerir` sobre quatro normas oficiais:

| Norma | Fragmentos | Com `numero_doc`/`ano_doc` | Chars |
|:---|---:|---:|---:|
| Decreto 3.048/1999 | 1.716 | 1.716 | 1.025.341 |
| Lei 8.080/1990 | 141 | 141 | 76.438 |
| EC 103/2019 | 116 | 116 | 85.397 |
| LC 142/2013 | 8 | 8 | 5.765 |
| **Total** | **1.981** | **1.981 (100 %)** | **1.192.941** |

- **Um defeito do parser apareceu por causa do corpus real:** o Planalto grafa `DECRETO No
  3.048` (o HTML usa `<u>o</u>`), e `parse_norm_header` devolvia três `None` — os 689
  dispositivos do maior documento ficariam sem norma. Corrigido em `legal_parser` com escopo
  local de caixa (`(?-i:N)o?`), para que "a lei no 8.080" em prosa não vire identidade.
- **A premissa do P2-30 estava parcialmente errada:** no HTML oficial o cabeçalho **não** se
  repete em cada fragmento (1 de 141 fragmentos da 8.080 cita "8.080" no texto, contra 14 de
  157 na apostila). O ganho de identidade vem do **metadado do documento** (100 % preenchido),
  não do texto do fragmento. A descrição original valia para o PDF do Planalto.
- **A dominância de documento é o novo problema de recuperação:** o Decreto 3.048 é 80 % dos
  fragmentos (1.716 de 2.141) e ocupa **64 dos 90** lugares de top-15 nas seis perguntas do
  mini-quiz sobre a 8.080. Curadoria de corpus não é só "trazer o oficial": tamanho relativo
  decide quem aparece no contexto. Vai para o backlog como item de recuperação.
- **Limiar absoluto continua sem separar** no corpus oficial (medido): melhor similaridade
  das perguntas que a base responde **0,761–0,829** contra **0,696–0,802** das que não
  respondem — faixas sobrepostas, com uma pergunta fora da base (pensão alimentícia, 0,802)
  acima de três legítimas. Confirma o ADR-0009 em base oficial: o R-16 tem de ser relativo.
- O custo de embedding é baixo: **1.981 fragmentos em ~53 s** (≈ 24 fragmentos/s, GPU).

## Alternativas descartadas

- **PDF sintético** (opção 1): fragilidade de pipeline e nenhum ganho de fidelidade.
- **Parser de HTML dentro da app** (opção 2): acopla a app a um formato de fonte e duplica o
  extrator; a conversão fora fica versionada e testável à parte.
- **Indexar só a Lei 8.080** (escopo mínimo): destravaria o R-16, mas o corpus oficial existe
  para o produto responder previdenciário; o custo medido (53 s) não justifica meio corpus.
