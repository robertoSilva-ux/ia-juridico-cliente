# ADR-0008 — Modelo padrão escolhido por orçamento de VRAM medido

- **Status:** aceito
- **Data:** 2026-10-16
- **Origem:** bancada em série (uma por vez, GPU sã) com o corpus de dev e o mini-quiz de
  7 perguntas, mais o incidente de hardware registrado no bloco 5 do `EVOLUCAO`

## Contexto

O produto roda LLM **local** na placa do cliente. Na máquina de desenvolvimento
(RTX 3050, 6 GB) a bancada anterior deixou claro que **o tamanho do modelo é uma decisão de
hardware, não de gosto**: um 7–8 B q4 a 8192 de contexto não cabe com o desktop e o servidor
de embeddings, e o Ollama então joga camadas na CPU **sem avisar** (respostas de 100–1800 s,
`ollama ps` mostrando `100% CPU`) ou morre com `CUDA error: unspecified launch failure`, e a
interface exibe "Erro interno ao processar a consulta." sem fontes e sem fact-check.

Medições que sustentam a decisão (uma bancada por vez; `ollama ps` conferido em cada série):

| modelo | recall | normas inventadas | `grounded` | recusa (armadilha) | mediana | onde rodou |
|:---|--:|--:|--:|--:|--:|:---|
| `phi4-mini:3.8b` | **0,56** | 2 | 7/14 | 0,21 | **7 s** | 100 % GPU |
| `gemma3:4b-it-qat` | 0,50 | 2 | 2/14 | 0,07 | 14 s | 95 % GPU |
| `qwen3:4b` | 0,50 | 1 | 2/14 | **0,29** | 125 s | 100 % GPU |
| `qwen2.5:7b @4096` | 0,38 | **0** | 9/14 | 0,07 | 17 s | 84 % GPU (16 % CPU) |

Duas medidas de VRAM fecham o orçamento: um modelo de 3,6–3,9 GB carregado (2,5 GB de pesos
+ KV cache a 8192) **empurra o `nomic-embed-text` para 74 % CPU** — e o embedding é usado em
toda pergunta e em todo fragmento da ingestão. Com o desktop aberto, a placa oferece ~5,06 GB
livres; um 7 B carrega ~5,5–6 GB nesse contexto, logo não cabe.

## Decisão

1. Modelo padrão de produção: **`phi4-mini:3.8b` com `LLM_NUM_CTX=8192`** (`LLM_MODEL` no
   `.env`/`.env.example`, confirmado pelo cliente em 2026-10-16).
2. Regra de dimensionamento para o servidor do cliente: **modelo de chat ≤ ~3,9 GB carregado
   a 8192 de contexto**, para não expulsar o servidor de embeddings da placa; com 6 GB e
   desktop, "4 B @8192" é o ponto de operação (um 7 B só a `LLM_NUM_CTX=4096`, e mesmo assim
   com 16 % das camadas em CPU).
3. O defeito do modelo escolhido — **inventar número de lei** (2 casos na bancada) — passa a ser
   coberto pela checagem de lastro e pelo portão de resposta (ADR-0007 e ADR-0009), não pela
   troca de modelo: os modelos maiores ou inventam igual (gemma3) ou custam latência/CPU.
4. Estado da GPU é **pré-requisito da medição**: série medida com a placa caída
   (`AER: can't recover`) é descartada, e latência só vale com `ollama ps` mostrando GPU.

## Consequências

- Latência mediana de 7–10 s por resposta (p95 medido: 10,6 s) na máquina de desenvolvimento —
  dentro do alvo de ≤ 20 s do `PLANO_REFINAMENTO_RAG`.
- O 4 B **não cumpre o contrato de saída de forma confiável** (escreve "exercise" por
  "exerce", mistura rótulos, recusa perguntas simples de forma instável — medido: 3 recusas em
  18 execuções de perguntas cuja resposta está na base). Isso é custo aceito: o portão de
  resposta (ADR-0009) transforma o defeito em recusa honesta ou em aviso, nunca em invenção
  exibida.
- Modelo maior **não** é a alavanca de qualidade aqui: nenhum dos medidos acerta a
  pergunta-armadilha (recusa correta entre 0,07 e 0,29) e o maior recall vem do 4 B.
- Reabrir a bancada é obrigatório quando mudar corpus, prompt ou hardware — o protocolo
  (uma bancada por vez, `ollama stop`, registrar `PROCESSOR`, medir a VRAM livre no momento)
  está em `EVOLUCAO.md` e em `.hermes/skills/.../qualidade-de-resposta-e-fact-check.md`.

## Alternativas consideradas

1. **`qwen2.5:7b` @4096** — único com 0 norma inventada, mas pior recall (0,38), 17 s e 16 %
   das camadas na CPU (não cabe). Descartado: o que ele oferecia (não inventar) o fact-check
   garante de qualquer forma, e o custo de VRAM é decisão de hardware do cliente.
2. **`qwen3:4b`** — melhor recusa na armadilha (0,29), mas 125 s por resposta por causa do
   *thinking mode*: inviável para chat.
3. **`gemma3:4b-it-qat`** — empatado em recall e mais lento, com 2 normas inventadas.
4. **Dividir o modelo entre CPU e GPU** — descartado: os 7 B já operam assim e o custo é de
   1 a 2 minutos por resposta, sem ganho mensurável de qualidade.
