# Comparativo final — melhoria RAG Legaliz.ai

## Estado publicado

- Branch: `main`
- Fase 3: `0853e55`
- Fase 4: `8b5cfad`
- Suíte final: **104 testes, 3 skips, OK**

## Recuperação por fase

| Etapa | source_hit@6 | keyword recall | Observação |
|---|---:|---:|---|
| Fase 1 / baseline | 5/6 | 15/28 | LC 142 não recuperada |
| Fase 2 / prompt | 5/6 | 14/28 | Guardrail de regime, sem correção de retrieval |
| Fase 3 / chunking | 5/6 | 15/28 | Artigos isolados; q5 melhorou |
| Fase 4 / regime | 4/6 | 16/28 | q4 e q6 corrigidas; q7/q9 regrediram |

Fonte dos dados: `relatorio_baseline_fase1_phi4_8192.json`, `relatorio_fase2_prompt_phi4_8192.json`, `relatorio_fase3_chunking_phi4_8192.json` e `relatorio_final_fase4_quiz9.json`.

## Ganhos comprovados da fase 4

- q4 — LC 142: `Lcp 142.pdf` passou de 0/1 para 1/1, nas quatro primeiras posições.
- q6 — salário-família: `Decreto 3.048-99.pdf` permaneceu em 1/1; o top-k real passou a conter **15/15** fontes do Decreto.
- Benchmark q6 com 20 iterações:
  - respostas com “24 anos”: **13/20 → 0/20**;
  - respostas com “14 anos”: **3/20 → 10/20**;
  - respostas com “21 anos”: **20/20 → 0/20**;
  - mediana: **17,2s → 17,0s**;
  - grounded: **5/20 → 3/20** — sem ganho de grounding do modelo.

## Limitações conhecidas

- q7 e q9 perderam `source_hit` no quiz final (ambas 0/1), embora tivessem 1/1 na fase 3.
- A causa provável é a injeção/priorização específica de regime RGPS, que concentra o top-k em documentos do Decreto 3.048 para consultas com marcadores amplos como “dependente” ou “segurado”.
- Isso não deve ser mascarado como melhoria universal: a fase 4 resolveu a mistura de regimes em q6 e a ausência da LC 142, mas introduziu uma regressão de cobertura em duas perguntas do quiz.
- Próxima melhoria recomendada, se autorizada: boost por intenção/dispositivo mais fino, preservando diversidade entre Decreto 3.048 e Lei 8.213, em vez de concentrar todas as 15 posições em uma única fonte.

## Verificação operacional

- Container `app` reconstruído após a fase 4.
- Probes reais executados contra o PostgreSQL/pgvector:
  - q6: 15/15 Decreto 3.048;
  - q4: quatro chunks da LC 142 no topo;
  - q5: Código Civil permaneceu no topo, sem boost indevido.
- Re-bench final q6: `bench_fase4_regime_q6_20x.json`.
- Quiz final de 9 perguntas: `relatorio_final_fase4_quiz9.json`.
