# ADR-0012 — Escopo por norma e teto por documento na recuperação

- **Status:** aceito
- **Data:** 2026-10-20
- **Origem:** P2-32 do [`BACKLOG.md`](../BACKLOG.md) ("dominância de documento na recuperação"),
  achado ao indexar o corpus oficial (P2-30, [ADR-0011](0011-corpus-oficial-em-texto.md))
- **Medido com:** `app/eval/medir_origem_contexto.py` (novo), `medir_portao.py`,
  `medir_a4_repetido.py`

## Contexto

Depois do corpus oficial, **um documento tem 86 % da base**: o Decreto 3.048 (RPS) são 1.716 dos
1.984 fragmentos, contra 141 da Lei 8.080, 116 da EC 103, 8 da LC 142. O primeiro estágio da
recuperação é similaridade de vetores pura (`embedding <=> query`), e similaridade **não sabe
quantos vizinhos um documento tem**: em pergunta sobre a Lei 8.080 o top-15 vinha quase todo do
regulamento previdenciário, e o contexto de 12.000 caracteres era consumido por uma norma que a
pergunta não pediu.

O sintoma não é erro de corpus nem do modelo — é **ranking**. Medido nas 6 perguntas do mini-quiz
sobre a 8.080 e em 7 perguntas-controle (6 sobre a 8.080 **sem citar artigo** + 1 sobre o próprio
decreto), com a base oficial (1.984 fragmentos), `TOP_K=15`, MMR ativo (λ=0,7):

| Cenário | Norma pedida entre os 3 primeiros | Lugares da norma no top-15 | Chars do maior documento no contexto |
|:---|:---|:---|:---|
| Caminho semântico, sem correção | **4 de 7 probes** (p3 em 5º, p4 em 4º, p5 em 10º) | **51 de 105** | d3048 = 50 % |
| Caminho do mini-quiz (5 de 6 itens citam artigo) | 6 de 6 | 14 de 26 | — |

A segunda linha é a armadilha do cartão: os itens do mini-quiz que citam "art. N da Lei 8.080"
caem na **busca por metadados** (R-15), que já filtra por `numero_doc` — eles passariam o critério
de aceite sem que nada fosse consertado, e a pergunta que não cita artigo continuaria recebendo
RPS. Medir só o mini-quiz mediria o caminho errado.

Três caminhos foram considerados, os três medidos:

1. **Teto de trechos por arquivo no top-K** (`MAX_CHUNKS_PER_DOC`).
2. **Diversificação na fusão** — MMR com λ menor e/ou penalidade por documento repetido.
3. **Escopo por norma na recuperação** — quando a pergunta nomeia a norma, filtrar por ela.

## Decisão

**Opções 3 + 1, nesta ordem de importância; opção 2 descartada por medição.**

- **Escopo por norma (`NORM_SCOPE_ENABLED`, ligado).** `regime._parse_norm_reference` extrai
  `(tipo_doc, numero_doc)` da pergunta **sem exigir artigo** ("O que a Lei 8.080 diz sobre
  consórcios?"). Quando há norma, `agent._buscar_com_escopo` consulta primeiro os trechos dela e
  **completa as vagas restantes com a busca livre** — o escopo nunca custa recall: norma ausente
  da base, ou com poucos trechos, devolve contexto completo mesmo assim.
- **Teto de trechos por arquivo (`MAX_CHUNKS_PER_DOC=4`, ligado).** Antes **e** depois do MMR:
  antes, para o pool que chega ao re-ranking já ter material de outros documentos; depois, porque
  o MMR reordena e traz de volta o que o teto tinha empurrado para o fim. **Não descarta nada** —
  quem passa do teto vai para o fim da lista e o corte de `MAX_CONTEXT_CHARS` decide se sobra
  espaço. O arquivo da norma pedida fica **isento**.
- **MMR com λ menor: descartado.** Medido λ ∈ {0,7; 0,5; 0,3; 0,1} sobre o mesmo pool semântico
  (12 perguntas): resultado **idêntico** nos quatro — 51 lugares da norma pedida, nas mesmas
  posições. O MMR atual mede redundância por similaridade de embedding, e fragmentos de um mesmo
  documento longo têm similaridade ~0,95 entre si: a penalidade vira constante e não muda a
  ordem. "Ligar mais MMR" não é remédio para dominância de documento.

## Consequências

- **Medido antes/depois, mesma base, mesmo código** (o A/B é por config: `NORM_SCOPE_ENABLED=false
  MAX_CHUNKS_PER_DOC=0` reproduz o comportamento anterior):

| Medida (13 perguntas: 6 do mini-quiz + 7 probes) | Antes | Depois |
|:---|:---|:---|
| Probes com a norma pedida entre os 3 primeiros | **4 de 7** | **7 de 7** |
| Lugares da norma pedida no top-15 (probes) | 51 de 105 | **90 de 105** |
| Lugares da norma pedida no top-15 (mini-quiz) | 14 de 26 | 24 de 26 |
| Chars do maior documento no contexto | d3048 = 50 % | l8080 = 72 % (é a norma pedida) |

  Com o caminho completo (HyDE + RRF): 7 de 7 e 92 de 105 — o escopo sobrevive à fusão.

- **A4 não regrediu:** `medir_a4_repetido` 13/18 → 13/18 (a rodada do meio deu 12/18 e a repetição
  devolveu 13/18; a diferença estava em **d5, cuja entrada é idêntica nos dois lados** — 1 trecho,
  372 chars, via metadados —, ou seja, ruído do `phi4-mini`, não efeito da mudança).
  `medir_portao`: A1 sem lastro **0**, A2 recusas corretas **7/7**, A4 4/6 nas duas pontas.
- **Quando a norma é nomeada, ela pode ocupar todo o top-K** (medido: 72–78 % dos caracteres).
  É consequência aceita: é o material que a pergunta pediu, e a alternativa (teto valendo também
  para ela) foi medida — **70 lugares** da norma em vez de 88, com a mesma taxa de acerto nos 3
  primeiros e a fatia de chars caindo para 40–73 %. Ficou de fora por cortar recall justamente
  onde a resposta se espalha por vários artigos da mesma lei; se o orçamento de contexto virar o
  problema (R-18, contexto por tokens), o caminho é medir de novo com esse teto ligado.
- **O escopo depende de a pergunta nomear a norma.** Sem nome ("quem exerce a direção do SUS?"),
  quem atua é o teto: ele espalha o contexto, mas não escolhe o documento certo — p1 e p2
  melhoraram de posição (1º) sem virar 15/15. Sinônimos e nomes por extenso ("Lei Orgânica da
  Saúde") não são reconhecidos: é dívida conhecida, com o mesmo instrumento para medir.
- **O teto espalha até onde o pool tem outro documento.** O pool é o top-45 semântico: se ele é
  95 % de um arquivo, o teto põe 4 trechos dele na frente, mais os poucos de outros documentos que
  existirem no pool — e o excedente volta depois deles. Medido no `smoke_dev` (pergunta de carência
  do RGPS, que nomeia norma nenhuma): 4 trechos do 3.048 na frente, Lei 8.213 em 1º, EC 103 na 6ª,
  e o resto do top-15 ainda do 3.048. Para espalhar mais longe é preciso **buscar mais candidatos**
  (`RERANK_TOP_K_MULTIPLIER`), não mudar o teto — e aí o custo é o tempo da busca.
- **A via de metadados continua devolvendo direto** (R-15): em 5 dos 6 itens do mini-quiz o
  contexto tem 1 a 5 trechos e nenhuma semântica. É o que explica d5 continuar recusada — a
  pergunta pede as leis revogadas pelo art. 55 e o caminho por metadados entrega **1 trecho**.
  Ranking não conserta isso; é o cartão do R-15.

## Alternativas descartadas

- **Só teto por arquivo** (opção 1 isolada): medido sobre o pool semântico das 13 perguntas — sobe
  os lugares da norma pedida de **64 para 90** (de 195) e **não** resolve o critério: 5 perguntas
  ficam com a norma fora dos 3 primeiros (d2 em 4º, d5 em 6º, p3 em 5º, p4 em 4º, p5 em 9º). O
  teto espalha; não sabe quem é a norma da pergunta.
- **Só escopo por norma** (opção 3 isolada): resolve o critério, mas deixa a pergunta sem norma
  nomeada exatamente como estava — e é o caso mais comum no uso real.
- **MMR com λ menor / penalidade de documento repetido no MMR** (opção 2): λ não muda nada
  (medido acima); uma penalidade por documento seria um terceiro parâmetro para calibrar sem
  instrumento que a justifique hoje.
- **Escopo rígido (só a norma pedida no contexto):** corta a resposta quando o dado está no
  regulamento — o próprio `_apply_regime_boost` documenta o caso do salário-família, em que o
  limite operacional está no decreto e não na lei.
- **Prior de documento por tamanho (penalizar quem tem muitos fragmentos):** resolveria o caso
  geral de forma suave, mas não há medição que diga qual penalidade, e o efeito colateral é
  rebaixar documento grande que é a resposta certa (o RPS responde previdenciário).
