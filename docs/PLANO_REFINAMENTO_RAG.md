# Plano de refinamento do RAG — fundamentação e recusa honesta

**Pedido:** refinar código, prompt, ingestão, chunk, gravação e recuperação para que a resposta
seja **100 % fundamentada no RAG** — ou que o sistema **diga honestamente que não encontrou**.

**Status:** **Fase 1 executada e medida** (R-1..R-8 ✅, ver §7) · **Fase 2 executada** (R-9..R-13 ✅)
· **R-24/R-25 planejados** em [`PLANO_R24_CHUNKER.md`](PLANO_R24_CHUNKER.md), aguardando autorização
· Fases 3–4 ⏳ aguardando decisão
· **Evidência medida em:** 2026-10-16 (09:5x–11:2x, GPU sã — boot 08:01, sem `AER: can't recover`;
suíte **268 casos em 14 módulos**, verdes também sob `env -i`; `phi4-mini:3.8b` em 100 % GPU).

---

## 1. O requisito traduzido em critério de aceite

| # | Critério | Como se verifica |
|:--|:---|:---|
| A1 | Resposta exibida ⇒ **toda frase factual tem `[n]` e o fragmento `[n]` sustenta o que ela afirma** | conjunto de perguntas com resposta na base; checagem por fragmento citado |
| A2 | Pergunta cuja resposta **não está na base** ⇒ o sistema **não apresenta resposta**: diz que não encontrou e o que faltou | pergunta-armadilha (tema fora do corpus) |
| A3 | Nada exibido como "similaridade" ou "fonte" que não tenha sido **medido** | nenhuma tela com 100,00 %; nenhuma fonte sem distância real ou rótulo de origem |
| A4 | O ganho não pode custar o produto: perguntas legítimas continuam respondidas | as 6 perguntas com resposta na base seguem respondidas (não viramos um recusador) |

**Alvo de topo:** com o modelo confirmado, no mini-quiz de dev (7 perguntas, a última armadilha):
**0 norma sem lastro exibida · armadilha recusada · 6/6 legítimas respondidas · p95 ≤ 20 s.**

---

## 2. Evidência medida hoje (não é leitura de código, é execução)

1. **Armadilha de honestidade** — "Qual o prazo de prescrição para a ação de usucapião
   extraordinária?" (tema fora da base), via `get_response`:
   resposta = *"A vigência não está indicada nos documentos recuperados."* (não responde),
   **15 fontes exibidas** com similaridade 66,9–69,0 %, e
   **`fact_check.all_grounded = True`** (`supported: 1`). Ou seja: hoje uma **não-resposta passa
   com selo verde** e leva 15 fontes de outra lei como se fossem evidência.
2. **Pergunta legítima** — "Segundo o art. 9º da Lei 8.080, quem exerce a direção do SUS na
   União?" → resposta correta em 6,6 s, **sem nenhuma citação `[n]`**, e `all_grounded = True`.
   O veredito é idêntico ao da não-resposta ⇒ **não serve como portão** (não distingue resposta
   certa de não-resposta).
3. **Faixas de distância se sobrepõem** (`nomic-embed-text`, sem limiar):
   6 perguntas **com** resposta na base → top-1 **0,150–0,273**;
   8 perguntas **fora** da base → top-1 **0,200–0,345**.
   Consequência: **nenhum limiar absoluto de distância separa "a base contém" de "não contém"**
   neste corpus (o de dev tem 1 documento: 119 dos 122 fragmentos são do mesmo PDF). O
   `SIMILARITY_THRESHOLD=0.80` não é portão — **tudo** passa e o `TOP_K=15` sempre enche.
4. **Distância fabricada.** `_metadata_search`/`_keyword_search` devolvem `distance = 0.0` e
   `retrieve_context` **retorna direto** — ignorando busca semântica, MMR e boost de regime.
   Medido: "Segundo o art. 9º, quais órgãos exercem a direção do SUS nos Estados e no DF?" →
   **1 fragmento**, 576 caracteres de contexto, `d = 0.0000` (a interface mostra
   **"Similaridade: 100.00 %"**), e o modelo completou com *"Lei nº 8.080, de 18 de maio de
   1990"* — data inventada.
5. **O prompt exige a seção "ARBITRAGEM DE REGIME JURÍDICO"**, que o modelo emite como frase e
   que o fact-check reprova (`partial`) — a causa dominante do falso positivo P1-9/P2-26.
6. **Configuração morta:** `FACT_CHECK_LLM_ENABLED` está em `config.py` e o docstring de
   `factcheck.py` a descreve, mas **nenhum código a lê** — a verificação semântica por LLM que a
   documentação promete não existe.
7. **Estado da gravação (base de dev):** 122 fragmentos · **120 sem `numero_doc`** · 49 sem
   `artigo` · `sources.numero_doc` NULL para a 8.080 (título degenerado `"Lei"`) · **1 fragmento
   de 17 caracteres** (`peticao.pdf`) indexado · fragmentos de 17 a 993 caracteres (média 515).
   O rodapé do professor (`Prof. Adriano de Oliveira www.estrategiaconcursos.com.br 25 de 64`)
   aparece dentro do **DOC 1 de toda consulta**.
8. **`_load_dispositivos_base` carrega a base inteira** no primeiro fact-check e valida dispositivo
   contra **todo o corpus** (não contra os documentos recuperados): é o P1-1 — OOM no container de
   512 MB e validação cruzada entre donos.
9. Contexto entregue: sempre 15 documentos, **6,0–8,6 mil caracteres** (bem abaixo dos 12 mil) —
   há orçamento para recuperar **menos e melhor**.

---

## 3. Diagnóstico por eixo

| Eixo | O que ajuda hoje | O que impede a garantia |
|:---|:---|:---|
| **Interface** | mostra a resposta e uma lista de fontes | `result["fact_check"]` é **calculado e descartado** (`main.py` usa só `answer`/`sources`): resposta com lei inventada aparece igual a resposta perfeita. Recusa não tem forma própria |
| **Pós-processamento** | checagem estrutural de citação `[n]` + par número/ano de norma (ADR-0007) | valida contra o **contexto agregado**, não contra o fragmento citado; frase **sem** `[n]` e sem número/dispositivo é "supported" (por isso a não-resposta passa); nenhum portão de exibição |
| **Recuperação** | híbrida (metadados, keyword, semântica), HyDE + RRF + MMR + boost de regime | via de metadados **substitui** a semântica e fabrica `distance = 0.0`; limiar absoluto 0.80 inócuo; `TOP_K=15` enche sempre |
| **Ingestão/chunk** | split por dispositivo (`Art. N`), normalização de whitespace | rodapé/cabeçalho repetido em **todo** fragmento; fragmento degenerado entra; identidade da norma **não é gravada** (só o nome do arquivo a carrega) |
| **Gravação** | escopo por dono, `ON CONFLICT` por (nome, dono), dedup de aplicação | sem `content_hash` único (P2-16); dedup lê todos os conteúdos do arquivo; sem índice de fragmento/página para rastrear a origem |
| **Prompt** | regras de ancoragem e de não inventar número | exige rótulos/seções que geram frases não verificáveis; não tem **contrato de recusa** com forma fixa; contexto não é declarado como dado (P1-8) |
| **Código/config** | — | estado global do LLM entre sessões (P1-2); orçamento de contexto por caracteres, sem contagem de tokens (P2-20); config morta (§2.6) |

**Tese do plano:** a garantia pedida **não se compra com um limiar de distância** (medido: não
separa) **nem com o fact-check atual** (medido: aprova não-resposta). Ela se compra com uma
**cadeia**: identidade da norma na ingestão → ruído fora → recuperação com origem declarada →
prompt com contrato de saída → **portão de exibição** por fragmento citado → interface que mostra
o veredito e a recusa.

---

## 4. Backlog R (com critério de aceite)

Legenda: ⏳ aberto · 🔄 em andamento · 🅿️ decisão do cliente/produto.

### Fase 1 — a garantia visível (não toca na base; risco baixo) — **EXECUTADA** ✅

| ID | Item | Onde | Critério de aceite | Status |
|:--|:---|:---|:---|:---|
| R-1 ✅ | **Exibir o veredito do lastro na resposta** | `app/main.py`, `app/ui_feedback.py` | resposta com sentença sem lastro mostra aviso visível (hoje o dado existe e é descartado); teste de UI com duplo | feito — `montar_resposta`/`render_resposta` + 8 testes |
| R-2 ✅ | **Forma própria de recusa** ("A base não contém … / procurado por …") renderizada como recusa, com as fontes que sobraram | `app/agent.py`, `app/ui_feedback.py` | 3 estados na prévia: respondida · recusada · erro de infraestrutura | feito — recusa canônica do sistema (`_texto_recusa`), 4 estados com teste |
| R-3 ✅ | **Nunca exibir similaridade fabricada**: `distance=0.0` deixa de virar "100,00 %"; listar/marcar só as fontes citadas | `app/main.py`, `app/regime.py`, `app/agent.py` | nenhuma tela mostra 100,00 %; resultado por dispositivo vem rotulado como tal | feito — `distance NULL` + `origem` na busca por dispositivo/keyword |
| R-4 ✅ | **Lastro por fragmento citado**: número/dispositivo conferido no conteúdo do `[n]` citado, não no contexto agregado | `app/factcheck.py` | teste novo reprova "35 anos" citado do art. 54 para pergunta de idade mínima; o caso 8080/2011 segue reprovado | feito — `lastro_fora_do_citado` (4 testes) |
| R-5 ✅ | **Resposta sem lastro verificável não é resposta** | `app/factcheck.py`, `app/agent.py` | a frase medida em §2.1 deixa de ser exibida como resposta | feito — recusa reconhecida na 1ª frase; `sem_fonte` vira **aviso** (medido: bloquear descartava resposta correta) |
| R-6 ✅ | **Portão de exibição + 1 regeneração com feedback** | `app/agent.py` | 0 norma sem lastro exibida; p95 ≤ 20 s | feito — **0** invenção exibida; p95 **10,6 s** (medido, 5 rodadas) |
| R-7 ✅ | **Contrato de saída verificável no prompt** | `app/prompts/system-role.md` | 20/20 respostas dentro do formato; nenhum número sem dispositivo citado | feito — contrato `[DOC n]`, recusa como último recurso, sem seção de regime obrigatória; teste de contrato no prompt |
| R-8 ✅ | **`FACT_CHECK_LLM_ENABLED`: implementar (checagem de suficiência) ou remover** | `app/config.py`, `app/agent.py` | nenhuma config promete o que não existe | implementado como **portão de suficiência** (medido: 7/7 legítimas liberadas, 4/6 fora da base recusadas); default passou a `true` |

### Fase 2 — a base (ingestão, chunk, gravação) — **EXECUTADA** ✅

| ID | Item | Onde | Critério de aceite | Status |
|:--|:---|:---|:---|:---|
| R-9 ✅ | **Identidade da norma por DOCUMENTO**: ler `LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990` no texto e gravar `numero_doc`/`ano_doc` em todos os fragmentos e em `sources` | `app/ingest.py`, `app/legal_parser.py` | 100 % dos fragmentos de um PDF com a identidade que o texto traz; fact-check deixa de depender do nome do arquivo | feito — `identidade_do_documento` (13 formatos reais + 10 testes); a citação "(Incluído pela Lei nº 12.401…)" **não** vira identidade |
| R-10 ✅ | **Remover cabeçalho/rodapé repetido entre páginas** (P2-29) | `app/ingest.py` | o rodapé do professor não aparece em fragmento nenhum; distâncias medidas antes/depois | feito — comparação com números normalizados (`… 25 de 64` = `… 26 de 64`); **preserva** a linha de identidade da norma repetida em toda página (é o ganho do corpus oficial, P2-30) |
| R-11 ✅ | **Descartar fragmento degenerado** | `app/ingest.py` | nenhum fragmento < N | **critério corrigido por medição**: fragmento que ficou **vazio** após a limpeza é descartado; **não se descarta por tamanho** — na base de dev os artigos "Art. 51. (Vetado)." têm 17 caracteres e são lei vigente |
| R-12 ✅ | **Dedup por `content_hash`** com índice único por (arquivo, dono) — P2-16 | `database/init.sql`, `database/migrate_documents_hash.sql`, `app/ingest.py` | reingestão idêntica não insere nada e não carrega todos os conteúdos em memória | feito — verificado em **Postgres real**: duplicata direta rejeitada pelo índice, `ON CONFLICT` da ingestão não erra, mesmo conteúdo de outro dono entra |
| R-13 ✅ | **Rastreabilidade**: guardar página/índice do fragmento | `app/ingest.py`, schema | a UI consegue apontar de qual página veio o trecho citado | feito — colunas `pagina` (1-based; ausente = NULL) e `ordem`, no banco real e nos testes |

### Fase 3 — recuperação

| ID | Item | Onde | Critério de aceite |
|:--|:---|:---|:---|
| R-14 | **Fim da distância fabricada**: `distance NULL` + `origem` ('dispositivo'/'keyword'/'semantico') | `app/regime.py`, `app/ranking.py` | busca por dispositivo não aparece com similaridade |
| R-15 | **A via de metadados não substitui a semântica**: fundir (RRF) em vez de retornar direto | `app/agent.py` | consulta com artigo volta a ter via semântica e boost de regime (medido: hoje 1 fragmento, 576 chars) |
| R-16 | **Portão relativo** no lugar do 0.80 absoluto (p.ex. "melhor distância + margem" e mínimo de fragmentos) | `app/agent.py`, `app/config.py` | medido no corpus oficial; em dev, registro explícito de que **não separa** (§2.3) |
| R-17 | **`_load_dispositivos_base` escopada por dono e limitada** (P1-1) | `app/factcheck.py` | nenhuma leitura sem `owner_id`/escopo; memória limitada; cache invalidado na ingestão |
| R-18 | **Contexto por tokens, não por caracteres** (P2-20) | `app/ranking.py`, `app/agent.py` | truncamento deixa de ser silencioso; a lista de fontes nunca inclui documento que o modelo não viu |

### Fase 4 — robustez (dívidas que a garantia expõe)

| ID | Item | Onde | Critério de aceite |
|:--|:---|:---|:---|
| R-19 | **Estado global do LLM entre sessões** (P1-2) — pior com a 2ª chamada do R-6 | `app/agent.py` | troca de modelo afeta só a sessão que trocou |
| R-20 | **Contexto é DADO, não instrução** (P1-8) + teste com fragmento contendo "ignore as instruções acima" | `app/prompts/`, `app/agent.py` | comportamento não muda com o fragmento hostil |
| R-21 | **Erro de infraestrutura ≠ erro interno** (P1-10): distinguir "GPU sem memória / indisponível" na interface | `app/agent.py`, `app/ollama_utils.py`, `app/main.py` | mensagem diz o que houve e o que fazer |

### Verificação contínua

| ID | Item | Critério de aceite |
|:--|:---|:---|
| R-22 | **Mini-quiz versionado no repo** (hoje vive só no scratch, fora do versionamento) com a pergunta-armadilha e métricas A1–A4 | roda em 1 comando (`app/eval/`) |
| R-23 | **Protocolo de medição antes/depois por fase**, uma bancada por vez, com o modelo confirmado | relatório por fase em `app/eval/relatorios/`; série cuja GPU não estiver sã é descartada |

### Achado durante a Fase 2 (medido no PDF real, ainda aberto)

| ID | Item | Onde | Critério de aceite |
|:--|:---|:---|:---|
| **R-24** | **O chunker descarta em silêncio 36 % do texto**: `split_legal_documents` só abre seção a partir do primeiro `Art. N` da página; o texto ANTERIOR ao primeiro dispositivo do documento cai em `if current_document is None: … continue`. Medido no PDF real da apostila (65 páginas): páginas 0–24 = **34.726 de 96.246 chars (36,1 %)** não entram em fragmento nenhum — inclui o título da lei, a capa e a lista de leis alteradoras. Efeito no produto: pergunta cuja resposta esteja nesse texto é **irrecuperável** (a IA vai recusar honestamente, mas deveria ter achado). Efeito no R-9: a identidade pelo texto depende de o cabeçalho sobreviver ao chunking. **Re-medido em 2026-10-16 — o número se confirma, e agora está decomposto:** 25 das 65 páginas não têm dispositivo e o primeiro está na **página 26** → **36.536 de 100.937 chars crus (36,2 %)** descartados. No líquido, o índice guarda **60,0 %** do PDF (60.584 chars em 109 fragmentos) e o R-24 responde por **31.453 chars (31,2 %)**; o resto da diferença é o rodapé repetido, que a R-10 tiraria de qualquer forma. O que se perde tem nome: capa e título, a lista cronológica das leis alteradoras, os comentários por artigo e a teoria esquematizada ("Descentralização: é o processo…"). Plano de correção, com as decisões que são suas: [`PLANO_R24_CHUNKER.md`](PLANO_R24_CHUNKER.md) | `app/ingest.py` | nenhum caractere do PDF sai do índice sem virar fragmento (preâmbulo/capa viram fragmento próprio, com `page`); medição de antes/depois do total de chars indexados |
| **R-25** | **A grafia ordinal sem ponto dos artigos 1º a 9º não é reconhecida como dispositivo.** `_ARTICLE_START` exige pontuação depois do número (`Art\.?\s*\d+[º°]?\s*[.\-–—]`), e a lei escreve `Art. 9º A direção do Sistema Único de Saúde…`. Medido no PDF real: **9 dispositivos no início de linha** nessa grafia (a regra atual reconhece **0**) contra **3 referências inline** (*"na forma do art. 2º"*) que a regra nova **não** pode capturar. Hoje não há perda comprovada — a art. 9º se salva pela regra de prefixo, porque divide a página com um `Art. 10.` —, mas uma página cujos únicos dispositivos estejam nessa grafia é tratada como continuação da anterior | `app/ingest.py` | marcador reconhecido no **início de linha** em grafia ordinal; referência inline no meio do texto **não** vira início de dispositivo (teste dos dois lados) |

---

## 5. Ordem, escopo e orçamento

| Fase | IDs | Esforço | O que muda para o usuário |
|:---|:---|:---|:---|
| 1 | R-1..R-8 | ~1 sessão | a resposta passa a vir com veredito, e a não-resposta vira recusa honesta |
| 2 | R-9..R-13 | ~1 sessão + reingestão | a base passa a saber **qual norma** cada fragmento é; some o ruído |
| 3 | R-14..R-18 | ~1 sessão | recuperação diz de onde veio e para de enganar; portão medido no corpus oficial |
| 4 | R-19..R-21 | ~½ sessão | falha de infraestrutura deixa de se disfarçar de resposta |

---

## 6. O que este plano **não** garante (limite declarado)

- **Lastro não é correção.** O caso medido "idade mínima em 2026 = 35 anos" (o art. 54 traz 35
  anos de **contribuição**, não idade): o número **existe** no fragmento citado, então a checagem
  de lastro não reprova — o defeito é de **inferência**. Para essa classe o que existe é prompt
  (arbitragem + âncora por dispositivo), portão de recusa e avaliação por quiz com gabarito — não
  uma garantia automática. Se o cliente exigir garantia técnica aqui, o caminho é
  **resposta extrativa** (copiar o dispositivo) ou um verificador por LLM (custo de latência).
- **A calibração da recusa não fecha no corpus de dev**: com **1 documento** na base, nenhuma
  pergunta é realmente "fora do corpus" (§2.3). Os números de recusa só valem medidos no corpus
  do cliente (Decreto 3.048, LC 142, EC 103) — ou com texto oficial trazido para dev.
- **Corpus continua sendo a maior alavanca** (P2-30): apostila esquematizada espalha número e ano
  da lei em fragmentos diferentes e põe rodapé de cursinho dentro do embedding. Ajustar prompt e
  código ajuda; trocar por texto oficial (Planalto) resolve de raiz — é decisão de operação com o
  cliente, não de código.

---

## 7. Fase 1 — executada (2026-10-16)

Decisão registrada no **ADR-0008** (modelo por orçamento de VRAM) e no **ADR-0009** (portão de
resposta e recusa honesta).

### Resultado medido (mini-quiz de 7 perguntas + 6 perguntas fora da base, GPU sã)

| Critério | Antes | Depois |
|:---|:---|:---|
| A1 resposta exibida com norma/dispositivo sem lastro | 1 resposta errada com selo verde | **0** |
| A2 pergunta cuja resposta não está na base → recusa honesta | 0 de 7 | **7 de 7** |
| A4 perguntas legítimas respondidas (3 iterações cada) | 6 de 6, com 2 citando ano inventado | **15 de 18 (83 %)** — recusas em d4 (2/3) e d5 (1/3) |
| Latência | mediana 7 s | mediana **7,9 s** · p95 **10,6 s** (alvo ≤ 20 s) |

### Defeitos encontrados DURANTE a implementação (e que só a medição mostrou)

1. **O verificador não aceitava o formato que o prompt manda usar.** O prompt exige citar
   `[DOC n]`; `_extract_citations` só reconhecia `[1]`. Toda resposta corretamente citada era
   reprovada como "sem fonte" → reescrita → recusa: **4 de 5 perguntas legítimas recusadas**
   (medido com a d1, que era respondida em 5 de 5 execuções isoladas). Corrigido, com teste.
2. **Bloquear resposta sem citação jogava fora resposta CORRETA.** A d2 respondia *"os municípios
   podem constituir consórcios…"* (correto, sem citação) e o texto era descartado; a reescrita
   desistia e o advogado recebia recusa. `sem_fonte` passou a ser **aviso**, não bloqueio.
3. **Retry que termina em recusa disparava uma terceira chamada** (recusa sobre recusa) e a
   resposta boa da primeira era perdida. Agora é **uma** segunda leitura, sempre, e nada mais.
4. **Distância fabricada**: busca por dispositivo devolvia `distance = 0.0` e a interface
   escrevia "Similaridade: 100,00 %" (R-3 fechado com `distance NULL` + `origem`).
5. **Recusa em prosa exibida como resposta**: *"A base não contém informações… pelo art. 55"*
   era classificada `fundamentada` (a menção ao art. 55 contava como "unidade verificável").
   A recusa passou a ser reconhecida pela primeira frase, com tolerância a deformação
   ("NÃO ENCONTRAR NA BASE").

### Limite que ficou em aberto (honesto)

**A4 = 83 %, não 100 %.** O `phi4-mini:3.8b` recusa de forma instável perguntas cuja resposta
está no material — sempre a mesma (d4: exige inferir de "(Incluído pela Lei nº 12.401, de 2011)"
qual lei incluiu o artigo) e às vezes uma simples (d5, 2/3; d1 oscila entre execuções). O portão
de suficiência diz "SIM" nesses casos e a segunda leitura não resolve: é limite do modelo de
3,8 B, não do portão. Caminhos: **Fase 2** (corpus oficial — o texto do Planalto traz
"Redação dada pela Lei nº 12.401/2011" junto ao dispositivo, e a identidade da norma em todos os
fragmentos), **Fase 3** (portão relativo + fim da via de metadados que substitui a semântica) e
uma fração de **fase 5** (resposta extrativa: devolver o próprio trecho quando o modelo não
souber concluir). Registrado também no ADR-0009.

### Instrumentos de medição

Mini-quiz, medidor do portão/recusa e medidor de A4 com repetição vivem em
`app/eval/` (`quiz_dev_lei8080.json`, `medir_portao.py`, `medir_a4_repetido.py`) — R-22
parcialmente atendido: o que falta é ligá-los a um alvo de `make` e a um critério no CI.

