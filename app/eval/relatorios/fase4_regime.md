# Fase 4 — boost de regime jurídico

## Implementação

- `legal_parser.py` reconhece `Lcp 142.pdf` como `lei_complementar/142`.
- `agent.py` infere sinais explícitos de regime (`LC 142`, RGPS, INSS, salário-família etc.).
- Candidatos compatíveis recebem `regime_score` antes do MMR.
- Documentos explicitamente citados são injetados por busca determinística, mesmo fora dos 45 candidatos semânticos.
- A injeção mescla por `id`, sem duplicar documentos e preservando o filtro de escopo.
- Para salário-família, o Decreto 3.048 recebe prioridade sobre a Lei 8.213 por conter o dispositivo regulamentador operacional (art. 83).

## Evidência de testes

- RED: `python3 -m unittest discover -s app/tests -p 'test_agent.py'` falhou com `ImportError: cannot import name '_infer_regime_profile'`.
- GREEN específico: 49 testes do agente + 22 do parser, OK.
- GREEN completo: `python3 -m unittest discover -s app/tests -p 'test_*.py'` → **104 testes, 3 skips, OK**.
- Imagem Docker reconstruída e probes executados contra o banco real.

## Probes reais

- q6 salário-família: **15/15** fontes no top-k são `Decreto 3.048-99.pdf`; art. 83/84/86/88 presentes.
- q4 LC 142: `Lcp 142.pdf` aparece nas **4 primeiras posições**, incluindo todos os seus chunks.
- q5 usucapião: permaneceu com `L10406compilada.pdf` no topo; sem boost indevido.

## Benchmark q6 — phi4-mini:3.8b, ctx=8192, 20 iterações

| Métrica | Fase 3 | Fase 4 |
|---|---:|---:|
| respostas grounded | ver arquivo fase 3 | ver arquivo fase 4 |
| mediana | ver arquivo fase 3 | ver arquivo fase 4 |
| duração total | ver arquivo fase 3 | 340,9s |

Os valores detalhados permanecem nos JSONs `bench_fase3_chunking_q6_20x.json` e `bench_fase4_regime_q6_20x.json`.
