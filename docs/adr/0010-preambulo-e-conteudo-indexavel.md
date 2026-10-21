# ADR-0010 — O preâmbulo é conteúdo indexável e rotulado

- **Status:** aceito
- **Data:** 2026-10-19 (decisão implementada e medida em 2026-10-16; registro escrito depois)
- **Origem:** R-24/R-25 do [`PLANO_REFINAMENTO_RAG.md`](../PLANO_REFINAMENTO_RAG.md), plano de
  correção em [`PLANO_R24_CHUNKER.md`](../PLANO_R24_CHUNKER.md) e medição da base reingerida

## Contexto

O `split_legal_documents` só abria seção a partir do primeiro `Art. N` da página; o texto
anterior a ele caía no `continue` de `if current_document is None` e **desaparecia do índice
sem aviso**. Medido na apostila de dev (65 páginas):

| | |
|:---|:---|
| PDF cru | 100.937 chars |
| indexado antes da correção | 60.584 chars em 109 fragmentos (**60,0 %**) |
| descartado pelo chunker | **31.453 chars (31,2 %)** — 25 das 65 páginas |
| o que estava lá | capa e título da lei, apresentação, **lista cronológica das leis que alteraram a 8.080**, comentários por artigo, teoria esquematizada (*"Descentralização: é o processo de transferência…"*) |

Três forças em jogo:

1. **Recusa honesta só é virtude quando o dado não existe na base.** O portão do ADR-0009
   recusava pergunta que o material respondia — porque o texto tinha sido descartado na
   ingestão. Isso é defeito do chunker, não do portão.
2. **O R-9 estava cego por construção.** A identidade da norma era lida da concatenação dos
   *fragmentos*; o que o chunker descartava era exatamente o cabeçalho (título da lei), então a
   leitura não tinha o que ler.
3. **R-25, no mesmo caminho.** `_ARTICLE_START` exigia pontuação depois do número e não
   reconhecia `Art. 9º A direção do Sistema Único de Saúde…` — a grafia que a lei realmente usa
   para os artigos 1º a 9º. Medido no PDF: 9 dispositivos no início de linha nessa grafia contra
   0 reconhecidos, e 3 referências inline (*"na forma do art. 2º"*) que a regra nova **não**
   pode capturar.

## Decisão

1. **`extrair_paginas` passa a ser a base do pipeline**: carrega o PDF, remove ruído repetido
   (R-10), normaliza, e devolve as páginas limpas. `process_pdf` compõe sobre ela. A identidade
   da norma (R-9) é lida dessas **páginas**, não do texto já fragmentado.
2. **O texto anterior ao primeiro dispositivo é preâmbulo, não lixo**: vira **seção própria, uma
   por página**, passa pelo splitter (1000/100) e entra no índice com
   `tipo_trecho='preambulo'` (coluna que já existia; `dispositivo` é o padrão) e `pagina` 1-based
   por fragmento (R-13).
3. **Fragmento de preâmbulo grava `artigo = NULL`** — número de artigo encontrado em prosa não é
   cabeçalho de dispositivo. A interface marca esses trechos como **"trecho de comentário, não é
   dispositivo"**, para não apresentar comentário de apostila como texto de lei.
4. **A âncora da grafia ordinal é a linha**: `_ARTICLE_START` aceita `Art. Nº ` (sem pontuação)
   apenas no início de linha; referência inline no meio do texto continua sem casar. As duas
   âncoras — pontuação depois do número **ou** ordinal no começo da linha — é o que preserva
   `Art. 10.` e não transforma `na forma do art. 2º` em início de seção.
5. **Reingestão exige apagar a fonte antes**: com `content_hash` + índice único
   `(file_name, COALESCE(owner_id, -1), content_hash)`, a segunda carga do mesmo arquivo é pulada
   pelo `ON CONFLICT DO NOTHING` e o produto reporta 0 fragmentos.

## Consequências

Medido na base de dev reingerida (`legal_db`, 2026-10-19), com a suíte e o `ruff` verdes:

| métrica | antes (119 frag.) | depois (157 frag.) |
|:---|--:|--:|
| fragmentos | 119 | **157** (141 `dispositivo` + 16 `preambulo`) |
| chars indexados | 60.584 | **94.563 (+56 %)** |
| cobertura do texto limpo (92.037 chars) | 65,8 % | **102,7 %** — o excedente é a sobreposição do splitter |
| páginas com amostra de 8-gramas ausente no índice | — | **0 de 65** |
| identidade da norma nos fragmentos | 0 de 119 | **157 de 157** (`numero_doc=8080`, `ano_doc=1990`) |

Qualidade (mesmo mini-quiz, mesma bancada, `phi4-mini:3.8b` @8192, `ollama ps` 100 % GPU):

| critério | antes | depois |
|:---|:---|:---|
| A1 resposta exibida com norma/dispositivo sem lastro | 0 | **0** |
| A2 pergunta fora da base → recusa honesta | 7/7 | **7/7** |
| A4 legítimas respondidas (3 iterações, 18 execuções) | 15/18 | **15/18** |
| latência mediana / p95 (A4) | 7,9 s / 10,6 s | **2,5 s / 12,2 s** |

- **O ganho é de cobertura, não de taxa de acerto**: as perguntas do mini-quiz já eram
  respondidas antes. O que mudou é a classe de pergunta **conceitual**, que antes recebia recusa
  honesta porque o texto não existia no índice: *"O que é descentralização no SUS?"* passa a `ok`
  (12,8 s, 15 fontes) e *"Quais leis alteraram a Lei 8.080?"* devolve a lista cronológica das
  páginas 3–4 — resposta correta que sai como `parcial` por `sem_fonte`, família **P1-9**
  (formato de citação), não falta de lastro no corpus.
- **O plano previu a fronteira errada, e a medição corrigiu**: esperava-se ~34,7 mil chars de
  preâmbulo nas páginas 1–25; a base tem **11.495 chars em 16 fragmentos, páginas 1–8**. Motivo:
  com o R-25 o primeiro dispositivo real do material está na **página 9** (`Art. 1º Esta lei
  regula…`), não na 26 — as páginas 9–25 seguem indexadas, agora dentro de seções de dispositivo
  (79 dos 141 têm `artigo` preenchido). Nada se perdeu; o rótulo `preambulo` cobre menos do que o
  previsto. **Medir a fronteira de novo é obrigatório em qualquer corpus novo.**
- **Limite registrado (dívida, não defeito medido)**: `factcheck._load_dispositivos_base` varre o
  conteúdo de **todos** os trechos por padrão de dispositivo, sem filtrar `tipo_trecho`. Em tese
  um número de artigo citado em comentário passaria a "existir" na base. Nesta base o efeito
  medido é **zero** (60 dispositivos vindos de fragmento `dispositivo`, 60 no total — o preâmbulo
  não acrescenta nenhum), mas o filtro não existe no código: fica como item de backlog para
  quando o corpus oficial chegar.
- **O que não melhorou**: o A4 continua falhando no **d4** (art. 19-B, 1/3 das execuções) — é
  instabilidade do modelo de 3,8 B diante de uma inferência, a mesma do baseline. Chunker não
  conserta isso; corpus oficial (P2-30) e recuperação (Fase 3) sim.
- Custo aceito: o preâmbulo é prosa didática e passa a competir pelos 15 lugares do `TOP_K`. Hoje
  a recuperação usa 6–12 mil dos 12 mil chars de `MAX_CONTEXT_CHARS`; se o A4 cair com corpus
  maior, a resposta é o **portão relativo (R-16)**, não reverter esta decisão.

## Alternativas consideradas

1. **Não indexar o preâmbulo e corrigir só a identidade** — descartado: deixaria a classe de
   pergunta conceitual irrecuperável de propósito, e o critério de aceite ("nenhum caractere sai
   do índice sem virar fragmento") não é atendido.
2. **Um fragmento por página, sem passar pelo splitter** — descartado: 25 páginas de 1.400+ chars
   entrariam inteiras, estourando o orçamento de contexto por trecho; o splitter mantém `pagina`
   e granularidade.
3. **Fragmentar o preâmbulo com o mesmo caminho dos dispositivos** (`tipo_trecho='dispositivo'`) —
   descartado: sem rótulo a interface apresenta comentário como texto de lei e o fact-check não
   tem como saber que ali não há dispositivo.
4. **Descartar fragmento curto** (a capa tem 88 chars) — descartado, e é a regra do R-11:
   `"Art. 51. (Vetado)."` tem 17 chars e é lei vigente. Descarta-se só o que ficou vazio.
5. **Aceitar a grafia ordinal em qualquer posição** — descartado: capturaria `na forma do art. 2º`
   e abriria seção no meio de uma frase. A âncora de linha é o que separa dispositivo de
   referência.
