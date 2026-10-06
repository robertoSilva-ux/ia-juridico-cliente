# Bancada noturna legaliz.ai — comparativo de modelos

20 respostas da q6 (salário-família, gabarito: 14 anos) por configuração.
Qualidade = taxa de acerto da idade + groundedness; velocidade = tempo por resposta.

| config | modelo | ctx | n | erro | t med (s) | t p95 (s) | grounded | q6 correta | idades citadas |
|---|---|---|---|---|---|---|---|---|---|
| gemma3_ctx8192_20x | gemma3:4b-it-qat | 8192 | 20 | 0 | 28.3 | 37.35 | 0.1 | 0.85 | {21: 19, 14: 17, 24: 13, 6: 1, 7: 1} |
| phi4_ctx8192_20x | phi4-mini:3.8b | 8192 | 20 | 0 | 12.2 | 17.16 | 0.5 | 0.35 | {21: 14, 14: 7, 24: 4} |
| qwen2507_ctxdef_20x | hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M | default | 20 | 0 | 28.8 | 31.47 | 0.45 | 0.35 | {21: 12, 14: 7, 18: 6, 25: 2, 13: 1, 20: 1} |
| qwen2507_ctx8192_20x | hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M | 8192 | 20 | 0 | 23.2 | 35.5 | 0.0 | 0.35 | {24: 20, 21: 20, 14: 7} |
| qwen3_ctxdef_20x | qwen3:4b | default | 8 | 0 | 105.2 | 122.8 | 0.875 | 0.25 | {21: 6, 14: 2, 6: 1, 7: 1} |
| llama3_ctxdef_20x | llama3:latest | default | 20 | 0 | 21.9 | 37.55 | 0.65 | 0.25 | {21: 7, 18: 6, 14: 5, 24: 1, 65: 1} |
| phi4_ctxdef_20x | phi4-mini:3.8b | default | 20 | 0 | 14.9 | 488.32 | 0.4 | 0.15 | {21: 16, 24: 6, 65: 4, 5: 3, 14: 3, 23: 1, 10: 1, 18: 1, 16: 1} |
| gemma3_ctxdef_20x | gemma3:4b-it-qat | default | 20 | 0 | 14.6 | 17.98 | 0.8 | 0.05 | {21: 18, 14: 1} |

## Quiz completo (6 perguntas) — runs repetidas

### gemma3_quizfull

| qid | runs | t med (s) | kw por run | grounded |
|---|---|---|---|---|
| q1 | 3 | 28.3 | 1/1/1 | 2/3 |
| q2 | 3 | 15.6 | 3/2/2 | 0/3 |
| q3 | 3 | 32.6 | 2/2/2 | 1/3 |
| q4 | 3 | 29.7 | 2/1/2 | 0/3 |
| q5 | 3 | 15.2 | 0/0/0 | 1/3 |
| q6 | 3 | 13.4 | 1/1/1 | 3/3 |

### phi4_quizfull

| qid | runs | t med (s) | kw por run | grounded |
|---|---|---|---|---|
| q1 | 3 | 15.5 | 2/1/1 | 2/3 |
| q2 | 3 | 17.0 | 3/2/3 | 2/3 |
| q3 | 3 | 15.4 | 2/2/2 | 2/3 |
| q4 | 3 | 21.2 | 1/1/1 | 0/3 |
| q5 | 3 | 11.5 | 0/0/0 | 1/3 |
| q6 | 3 | 14.9 | 3/1/1 | 1/3 |

### qwen2507_quizfull

| qid | runs | t med (s) | kw por run | grounded |
|---|---|---|---|---|
| q1 | 3 | 55.9 | 1/1/1 | 0/3 |
| q2 | 3 | 32.3 | 3/3/2 | 0/3 |
| q3 | 3 | 41.4 | 3/3/3 | 2/3 |
| q4 | 3 | 37.9 | 1/1/1 | 0/3 |
| q5 | 3 | 20.1 | 0/0/0 | 0/3 |
| q6 | 3 | 20.1 | 1/2/1 | 0/3 |

