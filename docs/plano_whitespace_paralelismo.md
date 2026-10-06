# Plano: Normalização de Whitespace + Paralelismo na Indexação

**Projeto:** Legaliz.ai (`~/codigos/legaliz.ai/legaliz.ai-mvp`)
**Data:** 2026-09-20
**Origem:** ajustes validados no Temporal Wolf (mesmo modelo de embedding, `nomic-embed-text`)

---

## Resumo executivo

Três melhorias, todas portadas do Temporal Wolf e adaptadas ao contexto jurídico:

| # | Mudança | Estado |
|---|---|---|
| 1 | **Normalização de whitespace** na ingestão | ✅ implementado |
| 2 | **Progresso unificado** (upload único e lote) | ✅ implementado |
| 3 | **Indexação em massa com N workers** | ✅ implementado |

Arquivos novos: `app/progress.py`, `app/scripts/indexar_lote.py`.
Arquivos alterados: `app/ingest.py`, `app/tests/test_ingest.py`.

---

## ⚠️ Correção de um diagnóstico anterior

Durante a investigação eu levantei a hipótese de que a base estava **mista** — 10.281
documentos antigos (≤ 21/08) supostamente sem o prefixo `search_document:`, contra 4.351
novos (14/09) com prefixo.

**Essa hipótese foi REFUTADA por evidência direta.** Amostrei um documento de cada período
e recalculei o embedding do mesmo texto com e sem prefixo:

| Grupo | cos(armazenado, SEM prefixo) | cos(armazenado, COM prefixo) |
|---|---:|---:|
| ANTIGO (id 10303) | 0,9329 | **1,000000** |
| NOVO (id 18522) | 0,9106 | **1,000000** |

Correlação de `1.000000` nos dois casos: os vetores armazenados foram gerados **com** o
prefixo, em ambos os períodos. A base está consistente — não há contaminação, e os
relatórios de avaliação das fases 1–4 permanecem válidos.

**Lição registrada:** `uploaded_at` indica quando a *linha* foi inserida, não quando o
*vetor* foi gerado. Inferir estado de dado a partir de metadado temporal é um erro. A
verificação empírica custou minutos e evitou reindexar 14.632 documentos sem motivo.

> **Consequência para o plano:** não é necessária reindexação de resgate. A normalização de
> whitespace só afeta documentos **novos**; os antigos permanecem com o texto original. Ver
> a seção "Decisão pendente" no fim.

---

## 1. Normalização de whitespace

### O problema

O `PyPDFLoader` produz texto com ruído que degrada o embedding e desperdiça orçamento de
tokens:

- Hifenização de quebra de linha (`aposen-\ntadoria`)
- Espaços múltiplos e tabulações
- Espaços não separáveis — NBSP, `\u00a0`, thin space
- Sequências longas de quebras de linha

Para o `nomic-embed-text`, `"aposen- tadoria"` e `"aposentadoria"` são tokens diferentes:
o vetor resultante descreve a *forma* errada do texto.

### A solução

`normalize_whitespace()` em `app/ingest.py`, aplicada **por página, antes do split
jurídico**. A ordem importa: normalizar depois do split faria o texto armazenado divergir
do texto que o `legal_parser` analisou.

Regras, nesta ordem:

1. NBSP e espaços Unicode → espaço ASCII
2. Hífen + quebra de linha → remove a quebra, **preserva o hífen**
3. Espaços/tabs repetidos → um espaço
4. Espaços em torno de quebras → removidos
5. 3+ quebras → no máximo 2 (preserva parágrafos)
6. `Art.83` / `Art.  83` → `Art. 83` (separador canônico)

### A ambiguidade do hífen — decisão documentada

Os dois casos abaixo são **textualmente idênticos** e exigem tratamentos opostos:

| Entrada | Correto | Natureza |
|---|---|---|
| `aposen-\ntadoria` | `aposentadoria` | hífen de quebra de linha |
| `salario-\nfamilia` | `salario-familia` | hífen legítimo da palavra |

Sem dicionário, não há como distinguir. **Decisão: preservar o hífen e remover apenas a
quebra.** No domínio jurídico, compostos hifenizados (`salário-família`, `regime-próprio`,
`bem-estar`) são semanticamente críticos; corrompê-los é pior que deixar uma palavra
partida, que o embedding absorve como ruído menor. A decisão está comentada no código para
não ser "corrigida" no futuro sem entender o trade-off.

### Critério de verificação

`normalize_whitespace` preserva o marcador `Art. N` reconhecido por `_ARTICLE_START` — o
teste `test_normalize_whitespace_preserva_marcador_de_artigo` cobre `Art.  83`, `Art.83`
(colado) e `Art. 83` (já correto). Isso impede que a limpeza quebre a detecção de
dispositivos da qual o chunking jurídico depende.

---

## 2. Progresso unificado

### O problema

A barra de progresso do Streamlit (`st.progress`) consumia um generator do
`store_in_postgres`, que reporta progresso **linear de um único arquivo**. Com vários
arquivos em paralelo, esse sinal não diz quanto do **trabalho total** foi concluído.

### A solução

`app/progress.py` com duas peças:

**`ProgressTracker`** — contador global thread-safe, com **pesos por item**. O peso importa:
um PDF de 200 MB e um de 0,5 MB não podem contar igual, ou a barra mente. Em
`indexar_lote`, o peso de cada arquivo é o **tamanho em MB**.

**`run_parallel`** — executa uma função sobre N itens com W threads, com `on_progress`
global e `on_result` por item. Com `workers=1` o caminho é serial explícito, sem pool:
**o mesmo código serve o upload único e o lote**, que é o que permite uma barra só.

Garantias implementadas:

- Falha num item **não** interrompe o lote; o erro é coletado em `on_result`
- Resultados preservados na ordem dos itens
- Callback de UI nunca derruba o lote (try/except)
- Progresso atinge exatamente 1.0

### Por que threads, e não processos

O gargalo é o Ollama serializando na GPU, e o trabalho é I/O-bound (HTTP + Postgres).
Threads evitam serializar chunks entre processos e mantêm um pool de conexões único.
Medido no Temporal Wolf: **2 workers = 1,67×**; 3–4 não melhoram (contenção na GPU). Por
isso `DEFAULT_WORKERS = 2`.

---

## 3. Indexação em massa

`app/ingest.py` ganhou `ingest_document()`: extração → normalização → split → dedup →
embedding → inserção, reportando progresso decomposto em duas fases:

- **0.0 → 0.5**: extração, normalização e split
- **0.5 → 1.0**: embeddings e inserção no banco

Isso evita o defeito de barras que ficam travadas em 0% durante o parse (a fase mais longa
em PDFs grandes) e só destravam no fim.

`app/scripts/indexar_lote.py` expõe isso como CLI, para rodadas headless:

```bash
# poucos arquivos
python3 scripts/indexar_lote.py livro1.pdf livro2.epub --workers 2

# lista (TAB separa caminho e nome lógico; sem TAB, usa o basename)
python3 scripts/indexar_lote.py --lista arquivos.txt --workers 2
```

---

## Execução e operação

### ⚠️ Rebuild obrigatório

O container `app` faz `COPY . .` no build, **sem bind-mount de código**. Toda alteração
exige:

```bash
docker compose build app && docker compose up -d app
```

### ⚠️ `setsid`, nunca `nohup`

Rodadas longas lançadas em background por uma ferramenta morrem quando a execução desta
termina — o supervisor encerra a árvore de processos. `nohup` **não** protege contra isso; é
preciso desvincular do process group:

```bash
setsid ./script.sh < /dev/null > /dev/null 2>&1 &
```

No Temporal Wolf esse defeito matou a indexação três vezes antes de ser diagnosticado.

---

## Verificação

| Teste | Resultado |
|---|---|
| `normalize_whitespace` (8 casos) | ✅ 8/8 |
| `ProgressTracker` com pesos | ✅ |
| `run_parallel`: workers=1 ≡ workers=2 | ✅ |
| `run_parallel`: erro isolado não derruba lote | ✅ |
| `run_parallel`: ordem preservada | ✅ |
| CLI `indexar_lote.py --help` no container | ✅ |
| Suíte unitária (`test_ingest`, `test_legal_parser`) | ✅ **34 testes OK** |

---

## Decisão pendente — reindexação retroativa

A normalização afeta apenas **documentos novos**. Os 14.632 já indexados mantêm o texto
original (com ruído de PDF).

Reindexar **não** é necessário por corrupção — a base está consistente (ver correção
acima). Mas há um argumento **de qualidade**: o texto antigo carrega o ruído que a
normalização agora remove, o que pode causar assimetria entre documentos antigos e novos na
mesma busca.

| Opção | Custo | Ganho |
|---|---|---|
| Não reindexar | zero | Documentos novos saem limpos; antigos mantêm ruído |
| Reindexar só o texto (sem re-embeddar) | baixo | Uniformiza o texto armazenado |
| Reindexar completo | alto | Uniformiza texto **e** vetores |

**Recomendação:** medir primeiro. Rodar o avaliador (`app/eval/run_eval.py`) com o `quiz`
atual antes de decidir — se o ruído não estiver afetando a recuperação, a reindexação é
esforço sem retorno. A decisão deve vir de dados, não de princípio.

---

## O que NÃO fazer

- **Não** reindexar por suspeita de base mista — a hipótese foi refutada.
- **Não** "melhorar" a regra do hífen para unir sempre: corrompe compostos jurídicos.
- **Não** normalizar depois do split: dessincroniza texto armazenado e analisado.
- **Não** usar `nohup` para rodadas longas: use `setsid`.
- **Não** subir mais de 3 workers: o Ollama serializa na GPU; acima de 2 há contenção.
