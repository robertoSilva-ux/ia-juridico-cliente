# ADR-0013 — O peso por regime sai do caminho de recuperação

- **Status:** aceito
- **Data:** 2026-10-20
- **Origem:** revisão do `app/regime.py` depois do [ADR-0012](0012-escopo-por-norma-e-teto-por-documento.md).
  A pergunta que abriu: "isso ainda serve para desambiguar RPPS de RGPS ou virou peso morto?"
- **Medido com:** `agent.retrieve_context` (A/B por monkeypatch em `_apply_regime_boost`),
  `agent.get_response` em 3 iterações por pergunta, base de dev com o corpus oficial
  (1.984 fragmentos)

## Contexto

`_apply_regime_boost` nasceu para desempatar **RPPS × RGPS** quando a base misturava Vade Mecum,
apostila e legislação esparsa: a mesma pergunta tem resposta diferente em cada regime e o modelo
escolhia pelo trecho mais parecido. A regra dá peso (+0,25) a normas do regime "preferido" e
desconto (−0,10) às "excluídas".

O que ela é hoje, lido do código:

- **Três normas, escritas à mão**: `decreto 3048`, `lei 8213`, `lei_complementar 142`. O caso
  `salário-família` tem peso próprio (+0,40) justificado em comentário.
- **Casamento por NOME DE ARQUIVO** (`decreto[^0-9]*3?\.?048`, `l8213`, `vade_mecum`) — e o Vade
  Mecum não está mais na base.
- **`excluded` inclui emenda e constituição** sempre que a pergunta tem marcador de RGPS. Mas a
  **EC 103/2019 é norma que altera o RGPS** e a Constituição (art. 201) é a base dele: a exclusão
  derruba justamente a fonte que pode responder.
- **RPPS nunca foi implementado**: não existe marcador de regime próprio no código (`grep rpps`
  só acha texto em relatórios antigos de bench). O que existe é "RGPS ganha peso".
- **Assimetria de cobertura**: para saúde/SUS o perfil inferido é `{'preferred': [], 'excluded':
  []}` — a regra **nunca atua** em pergunta sobre a Lei 8.080, e é ali que a dominância do
  Decreto 3.048 aparecia.

## Medições

Três experimentos, mesma base e mesmo código, alternando **só** o peso:

**1. Posição da norma pedida no top-15 (11 perguntas: 5 do mini-quiz, RGPS e RPPS)**

| Caso | Com peso | Sem peso |
|:---|:---:|:---:|
| d1, d2, d3, d5, d6 (Lei 8.080) | 1 | 1 |
| "O que é descentralização no SUS?" | 13 | 13 |
| Carência / alíquota / pensão (RGPS) | 0 no top-15 | 0 no top-15 |
| Idade mínima / abono (RPPS) | 1 | 1 |

Empate em **11 de 11**.

**2. A4 do produto nas perguntas do mini-quiz (6 perguntas × 3 iterações)**

| | Com peso | Sem peso |
|:---|:---:|:---:|
| Respondidas (ok + parcial) | 12/18 | 12/18 |
| Mediana de latência | 2,5 s | 2,3 s |

Empate caso por caso (d1, d2, d3, d6 respondidas; d4 e d5 recusadas nas duas pontas). Explica-se:
o mini-quiz é todo sobre a 8.080, onde o perfil é vazio — **testar o peso ali não prova nada**.

**3. A4 nas perguntas que ATIVAM o perfil (RGPS/RPPS, 4 perguntas × 3 iterações)**

| | Com peso | Sem peso |
|:---|:---:|:---:|
| Respondidas | 6/12 | **7/12** |
| Resposta cita a norma esperada | 4/12 | 1/12 |

O número de citações parecia defender o peso. **Não defende: é artefato.** Medindo o contexto
recuperado nas mesmas perguntas:

| Pergunta | Com peso (normas no contexto) | Sem peso |
|:---|:---|:---|
| Dependentes de pensão por morte | **só** decreto 3048 (15/15) | 3048 + emenda 103 + LC 142 |
| Cota do salário-família | **só** decreto 3048 | 3048 + emenda 103 |
| Carência por tempo de contribuição | 3048 + lei 8213 | 3048 + emenda 103 + 8213 |

O peso **estreita o contexto** para o regime preferido e expulsa o resto. A taxa de citação sobe
porque o modelo cita o único documento que recebeu — não porque acertou o regime. É a mesma
dominância de documento que o P2-32 acabou de corrigir, reintroduzida por outra porta.

## Decisão

`REGIME_BOOST_ENABLED` passa a existir em `app/config.py` com **default `false`**: o peso sai do
caminho de recuperação. A função `_apply_regime_boost` **não é apagada** — fica atrás da flag,
porque é o instrumento de A/B e porque o caso `salário-família` está documentado nela. Quem quiser
reproduzir o comportamento antigo liga a variável de ambiente.

O que **não** muda: `_parse_article_reference` e `_metadata_search` continuam. Eles não são peso
por regime — são busca determinística por artigo/norma, e são o alvo do **R-15**, não deste ADR.
`_parse_norm_reference` (novo, do ADR-0012) é quem passa a carregar a noção de "a pergunta nomeia
esta norma".

## Consequências

- O contexto deixa de ser estreitado para a norma "do regime": em pergunta de RGPS voltam a
  aparecer EC 103 e LC 142, que é o que o R-15/R-16 e o próprio ADR-0012 esperam.
- Desambiguar regime passa a ser responsabilidade de **corpus + escopo por norma** (ADR-0012), não
  de reordenação por heurística. Quando a pergunta nomeia a lei, o escopo resolve; quando não
  nomeia, o caminho é melhorar a pergunta/corpus, não adivinhar regime.
- **Dívida declarada**: "Lei Orgânica da Saúde" e outros nomes por extenso não são reconhecidos
  pelo escopo, e a pergunta sem norma nomeada volta a depender só do ranking — é o mesmo limite
  já registrado no ADR-0012, agora sem a muleta do peso.
- O A4 medido **não regrediu** com o peso desligado (12/18 no mini-quiz, 7/12 nas de RGPS contra
  6/12) — mas esse número tem ruído do `phi4-mini`; a decisão se apoia no mecanismo medido
  (contexto estreitado), não na diferença de 1 caso.

## Alternativas descartadas

- **Apagar o código do peso**: perde o instrumento de A/B e o caso `salário-família` documentado;
  a flag custa uma linha e mantém a reprodutibilidade.
- **Corrigir pontualmente** (tirar emenda/constituição do `excluded`, acrescentar marcador de SUS):
  trata dois sintomas e mantém o mecanismo — reordenar por heurística de regime — cujo efeito
  medido é estreitar contexto.
- **Mover a desambiguação para o prompt**: não há medição que sustente; o portão de suficiência
  (ADR-0009) já cobre "não encontrei" e o custo é mais uma chamada de LLM por pergunta.
