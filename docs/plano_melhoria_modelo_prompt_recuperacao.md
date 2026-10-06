# Plano de Melhoria: Modelo × Prompt × Recuperação

**Base:** bancada noturna 2026-09-12 (5 modelos, 20 iterações/config, 214 respostas medidas —
`app/eval/relatorios/relatorio_bancada_noturna.md`) + diagnóstico do confusor q6.

## Diagnóstico (o que os dados dizem)

| Achado | Evidência |
|---|---|
| Gargalo não é o modelo — é a RECUPERAÇÃO | nenhum config passou de ~50% de grounding consistente; todos os 4B erram a mesma pergunta do mesmo jeito |
| Conflito de regimes é a falha nº 1 | q6 (salário-família, RGPS): 14 anos (art. 83 do Decreto 3.048/99). Confusores: **21 anos** (art. 16 — dependência p/ pensão, RGPS) e **24 anos** (art. 197 — estudante, regime próprio/Lei 8.112, colado no Vade Mecum) |
| O contexto maior piora — exceto no phi4 | qwen2507@8192 citou "24 anos" em 20/20 (contaminação total); gemma3@8192 dobra latência (14.6→28.3s); **phi4@8192 é o único onde 8192 ganha em tudo**: mais rápido (12.2s), mais grounded (0.40→0.50), mais acerto (15%→35%), "24 anos" só 4/20 |
| Prompt não âncora citações | respostas citam idade SEM citação de chunk; gemma3@8192 acerta a idade em 85% mas grounded 0.10 (mistura 14+21+24 sem arbitrar) |
| Chunking por caracteres fragmenta dispositivos | `RecursiveCharacterTextSplitter(1000/100)` pode partir o art. 83 no meio, tirando "quatorze anos" do chunk recuperado |
| Eval não mede recuperação isoladamente | quiz mede só a resposta; sem `expected_sources`, não dá pra separar "recuperou errado" de "gerou errado" |

## Configuração de produção escolhida (já definida pelos dados)

**phi4-mini:3.8b + num_ctx=8192** (único config onde contexto maior melhora qualidade E latência;
VRAM ~2.5GB, sobra folga na RTX 3050 6GB). Fallback: qwen2507@4096 (23-29s, grounded 0.45).

---

## Eixo A — Modelo (baixo esforço, já decidido)

1. **A1. Fixar produção:** `LLM_MODEL=phi4-mini:3.8b`, `LLM_NUM_CTX=8192` no compose/env.
   Critério: feito no PR de produção.
2. **A2. Re-bench pós-fases:** reabrir a bancada (infra pronta: `benchmark_models.py` +
   `consolidate_bench.py`) após cada fase do plano, mesmo protocolo (20 iterações q6 + quiz×3).
   Critério: comparativo novo em `relatorios/` a cada fase.

## Eixo B — Prompt (1 dia, sem risco de overfit se genérico)

3. **B1. Instruções de arbitragem de regime (genéricas, SEM a resposta da q6):**
   "A base contém normas de regimes distintos (RGPS = Lei 8.213/91 + Decreto 3.048/99; regime
   próprio dos servidores = Lei 8.112/90; constituição). Identifique a que regime a pergunta se
   aplica; quando chunks de regimes diferentes conflitarem, use o regime aplicável e DIGA qual
   descartou. Nunca misture prazos de regimes diferentes na mesma conclusão."
   Anti-overfit: instrução vale para qualquer pergunta de conflito, não cita salário-família.
   Critério: q6 20x → "24 anos" ≤ 2/20 e conclusão única (uma idade, não três).
4. **B2. Âncora obrigatória de citação:** "Todo número (idade, prazo, valor) na resposta deve
   estar presente no chunk citado [n] que o sustenta; número sem chunk citado é proibido."
   Critério: grounded ≥ 0.7 nas 20 iterações.
5. **B3. Regeneração com feedback (só se B1+B2 não bastarem):** o fact-check estrutural já
   detecta número desancorado (`_canonicalizar_numeros`); ao detectar violação, 1 retry passando
   as sentenças reprovadas ao modelo ("reescreva ancorado, ou recuse"). Custo: +1 chamada só
   nas respostas ruins. Critério: grounded ≥ 0.8 com p95 ≤ 20s mantido.

## Eixo C — Recuperação (o salto real, 2-3 dias)

6. **C1. Medir recuperação isolada (PRIMEIRO):** adicionar `expected_sources` ao quiz
   (q6: arquivo/segmento do art. 83 do Decreto 3.048/99) e métrica hit@k no `run_eval.py`.
   Sem isso não dá pra saber se o erro é recuperação ou geração. Critério: baseline phi4@8192
   medido antes de qualquer mudança.
7. **C2. Chunking por dispositivo jurídico:** trocar/ajustar splitter para preservar artigos
   inteiros (split por `Art\. \d+` com teto de tamanho; chars 1000/100 como fallback). Reingerir.
   Critério: art. 83 completo em 1 chunk; hit@k do art. 83 sobe.
8. **C3. Metadados de regime por documento:** na ingestão, classificar cada documento
   (rgps / regime_proprio / constituicao / outros) — regras simples sobre o nome/arquivo bastam
   para o Vade Mecum. Critério: 100% dos chunks com `doc_class` preenchido.
9. **C4. Boost/filtro de regime no retrieve:** se a query (ou classificador por regras)
   indicar RGPS, boostar `doc_class=rgps` e rebaixar `regime_proprio` no reranker (antes do MMR).
   Genérico: vale para qualquer conflito de regime. Critério: "24 anos" citado ≤ 2/20 e
   grounded ≥ 0.8, sem piorar as outras 5 perguntas do quiz.
10. **C5. Ampliar quiz anti-overfit:** adicionar 3-5 perguntas de idade/prazo de regimes
    diferentes (ex.: tempo de contribuição RGPS, prazo do regime próprio) com gabarito e
    `expected_sources`. Nenhuma fase pode melhorar a q6 piorando estas. Critério: quiz ≥ 9
    perguntas cobrindo os 3 regimes.

## Sequenciamento e orçamento de tempo

| Fase | Passos | Esforço | Saída medível |
|---|---|---|---|
| 0. Fixar produção | A1 | 15 min | config no compose |
| 1. Instrumentar | C1, C5 | ½ dia | quiz ≥9 perguntas + baseline hit@k phi4@8192 |
| 2. Prompt | B1, B2 | ½ dia | 20x q6: grounded ≥0.7, "24" ≤2/20 |
| 3. Chunking | C2 | ½-1 dia (reingestão) | hit@k art. 83 sobe; grounded + |
| 4. Regime no retrieve | C3, C4 | 1 dia | grounded ≥0.8; acerto q6 ≥80% |
| 5. Retry com feedback | B3 | ½ dia (só se preciso) | grounded ≥0.8, p95 ≤20s |
| 6. Re-bench final | A2 | automático | `relatorio_bancada_noturna.md` v2 |

**Alvo final:** acerto q6-equivalente ≥80%, grounding ≥0.8, p95 ≤20s no phi4-mini@8192,
sem regressão nas demais perguntas. Se a fase 4 atingir o alvo, a 5 é descartada.

## O que NÃO fazer (decisões explícitas)

- Não trocar de modelo de novo antes da fase 4 — os dados mostram que os 5 falham juntos
  no mesmo confusor; outro modelo 4B só muda o modo de erro.
- Não usar `num_ctx=8192` "no geral" — só ajudou o phi4; nos outros dobra latência sem ganho.
- Não colocar a resposta da q6 no prompt (few-shot com o gabarito = overfit de avaliação).
- Não ativar `FACT_CHECK_LLM_ENABLED` ainda (dobra latência) — o fact-check estrutural
  gratuito + regeneração sob demanda (B3) cobre o caso.
