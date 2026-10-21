# Plano de correção do R-24 — o chunker que descarta o preâmbulo

**Status:** ✅ **executado e medido** (código em 2026-10-16, medição na base reingerida em
2026-10-19). Decisão registrada no [`adr/0010-preambulo-e-conteudo-indexavel.md`](adr/0010-preambulo-e-conteudo-indexavel.md);
diário do bloco em [`EVOLUCAO.md`](EVOLUCAO.md) §"Bloco 8". Os passos 1–6 da seção 5 estão fechados,
com **uma correção da medição**: a fronteira do preâmbulo é a **página 9**, não a 26 — com o R-25 a
grafia ordinal do `Art. 1º` é reconhecida e o preâmbulo fica nas páginas 1–8 (11.495 chars), não nas
1–25 (34,7 mil). O número de cobertura não muda (0 de 65 páginas fora do índice).
**Origem:** [`PLANO_REFINAMENTO_RAG.md`](PLANO_REFINAMENTO_RAG.md) §4 — R-24, achado durante a Fase 2.
**Medição de referência:** 2026-10-16, `~/Downloads/LEI-8080-ESQUEMATIZADA1.pdf` — o mesmo arquivo
que estava na base. Os números da seção 1 são o **defeito** (antes); os de depois estão no ADR-0010.

---

## 1. O defeito, medido

| etapa | chars | do PDF |
|:---|--:|--:|
| PDF cru (65 páginas) | 100.937 | 100 % |
| limpeza R-10 (rodapé repetido + espaços) | −8.900 | −8,8 % — remoção **justificada** |
| indexado hoje (109 fragmentos) | 60.584 | 60,0 % |
| **descartado sem virar fragmento** | **31.453** | **31,2 %** |

**25 das 65 páginas não têm nenhum dispositivo**; o primeiro `Art. N` aparece na **página 26**:
36.536 chars (36,2 % do texto cru) caem no `continue` de `split_legal_documents`
(`app/ingest.py:225–231`), que só abre seção a partir do primeiro dispositivo detectado. Da primeira
página com dispositivo em diante o *prefixo* dela é preservado (linhas 233–237) — é o que hoje salva
a art. 9º.

O que se perde, por página (medido): capa e título da lei (p1), a apresentação do professor (p2),
**a lista cronológica das leis e decretos que alteraram a 8.080** (p3–4), os **comentários por
artigo** (p13+), a **teoria esquematizada** (p25: *"Descentralização: é o processo de transferência…"*).
Neste material o que cai é o **contexto conceitual** — perguntas como *"o que é descentralização?"*
hoje recebem **recusa honesta onde havia resposta**. É o único modo de falha em que a recusa do
portão (ADR-0009) é um defeito, não uma virtude.

### Dois defeitos no mesmo caminho

- **R-25 — a grafia sem ponto dos artigos 1º a 9º não é reconhecida.** A regex
  `(?<!\w)Art\.?\s*\d+[º°]?\s*[.\-–—]` exige pontuação depois do número, mas a lei escreve
  `Art. 9º A direção do Sistema Único de Saúde…`. Medido no PDF: **9 dispositivos no início de
  linha** nessa grafia (a regra atual reconhece **0**) contra **3 referências inline** (*"na forma do
  art. 2º"*) que a regra nova **não** pode capturar. Neste arquivo a art. 9º não se perde (a página
  dele também tem um `Art. 10.` e a regra de prefixo o preserva) — é fragilidade, não perda
  verificada.
- **A identidade da norma é lida do texto dos FRAGMENTOS**, não das páginas cruas:
  `app/ingest.py:303–307` junta `chunks` e só então chama `identidade_do_documento`. O que o R-24
  descarta é, portanto, invisível para o R-9. **Ressalva de honestidade:** os 119 fragmentos da
  apostila são **anteriores** ao R-9, então o efeito neste documento *não está medido* — o que está
  verificado é o caminho de código. Depois desta correção a medição passa a ter o que medir.

---

## 2. Critério de aceite (do plano-mestre, mantido)

> nenhum caractere do PDF sai do índice sem virar fragmento (preâmbulo/capa viram fragmento próprio,
> com `page`); medição de antes/depois do total de chars indexados

Métricas que eu meço **antes** de dizer "pronto":

1. **Cobertura**: chars indexados ÷ chars limpos ≥ **99 %** (a diferença só pode ser o rodapé repetido).
2. **Por página**: para cada uma das 65 páginas, uma amostra de **8-gramas** do texto limpo aparece no
   índice. *(A checagem anterior comparava 50 chars com espaços colapsados contra um índice com
   `\n` — dava falso positivo; por isso a troca por n-grama.)*
3. **Identidade**: `sources.numero_doc` da apostila passa a `8080` com `ano_doc=1990` lido do texto —
   ou o log diz por que não achou. *(Número: 22 páginas. Data: 1×, página 64.)*
4. **Recuperação não piora**: mini-quiz de `app/eval/` (A1/A2/A4/p95) medido **na mesma bancada**.
5. Suíte verde com os testes novos + `ruff` limpo.

---

## 3. Decisões que são suas

| # | Decisão | Opções | Recomendação |
|:--|:---|:---|:---|
| **D1** | O que fazer com o preâmbulo | (a) não indexar e só corrigir a identidade · (b) um fragmento por página · (c) fragmentar com o splitter (1000/100) | **(c)** — atende o critério, guarda `pagina` por fragmento e não estoura o orçamento de contexto |
| **D2** | Como marcar esses fragmentos | (a) não marcar · (b) `tipo_doc='preambulo'` · (c) campo novo em `metadata` | **(b)** — a coluna já existe; a interface pode dizer "trecho de comentário" e o fact-check sabe que ali não há dispositivo |
| **D3** | Corrigir a grafia ordinal agora | (a) junto · (b) bloco próprio | **(a) junto** — poucas linhas, com teste dos dois lados (o que deve e o que **não** deve casar) |
| **D4** | Reingerir a base de dev | (a) apagando a fonte antes · (b) só com arquivo novo | **(a)** — o `ON CONFLICT (file_name, owner, content_hash) DO NOTHING` **pularia** a reingestão (mesmo arquivo, mesmo hash) e a ingestão reportaria 0 fragmentos; apagar a fonte antes é o caminho |
| **D5** | Onde registrar a decisão | (a) ADR novo (0010) · (b) estender o ADR-0009 | **(a) ADR-0010** — "preâmbulo é conteúdo indexável e rotulado" é decisão de arquitetura com consequência no retrieval |

---

## 4. O que muda, arquivo por arquivo, com o teste de cada coisa

| # | Onde | Mudança | Teste |
|:--|:---|:---|:---|
| 1 | `app/ingest.py` | `extrair_paginas(file_path)` (loader + R-10 + normalização) passa a ser a base; `process_pdf` compõe sobre ela | `test_ingest`: páginas limpas, na ordem, com `pagina` 1-based |
| 2 | `app/ingest.py` | identidade lida das **páginas cruas** (não do texto concatenado dos fragmentos) | PDF cujo título só existe na página 1 → identidade achada; PDF sem título → cai no nome do arquivo, sem exceção |
| 3 | `app/ingest.py` | preâmbulo (texto antes do 1º dispositivo) vira **seção própria** e passa pelo splitter, com `tipo_doc='preambulo'` e `pagina` da página onde o fragmento começa | fixture de 3 páginas com dispositivo só na 3ª: o texto das páginas 1–2 aparece em fragmento, marcado, com `pagina` 1 e 2; e o caso "documento sem dispositivo nenhum" segue no caminho antigo (regressão) |
| 4 | `app/ingest.py` | `_ARTICLE_START` aceita o marcador **no início de linha** em grafia ordinal sem pontuação | `"Art. 9º A direção…"` no início de linha → é marcador; `"na forma do art. 2º"` no meio → **não** é; `"Art. 10."` e `"art. 198 da Constituição"` mantêm o comportamento atual |
| 5 | `app/factcheck.py` | fragmento de preâmbulo **não** serve como lastro de *dispositivo* (não tem `artigo`), mas **serve** como lastro de *identidade de norma* (é a capa/título que carrega "Lei 8.080") | teste: citação a fragmento de preâmbulo não passa como dispositivo; a identidade da norma continua valendo (ADR-0007) |
| 6 | `app/main.py`, `app/ui_feedback.py` | a lista de fontes mostra "trecho de comentário" para `tipo_doc='preambulo'` | teste de UI com duplo fiel (convenção do repo) |

---

## 5. Ordem de execução (passos pequenos, cada um revisável sozinho)

| Passo | O que entra | Pronto quando |
|:--|:---|:---|
| 1 | `extrair_paginas` + identidade das páginas cruas | testes novos verdes; reingestão **de um arquivo de teste** grava `numero_doc`/`ano_doc` |
| 2 | Preâmbulo vira fragmento marcado (`tipo_doc`, `pagina`) | fixture sintética cobre o caso; nenhuma perda de página |
| 3 | Grafia ordinal no início de linha | testes dos dois lados (casa / não casa) |
| 4 | Reingestão da apostila (apagando a fonte antes) + medição de cobertura por página | cobertura ≥ 99 % das páginas e do total limpo |
| 5 | Rótulo na interface + regra de lastro do preâmbulo | testes de UI e de fact-check verdes |
| 6 | Medição final do mini-quiz na mesma bancada + docs (EVOLUCAO, plano-mestre, ADR-0010) | A4/p95 medidos e registrados; suíte e `ruff` limpos |

**Execução:** passos 1–5 entraram em 2026-10-16 (`9876a7a`, `d836fb8`) — **com uma ressalva no
passo 5**: o rótulo da interface entrou, mas a regra de "preâmbulo não serve de lastro de
dispositivo" **não** foi implementada em `factcheck._load_dispositivos_base`. Medido na base de dev o
efeito é **zero** (o preâmbulo não acrescenta nenhum dispositivo ao cache), e fica como dívida
registrada no ADR-0010 para o corpus oficial. O passo 6 foi medido em 2026-10-19 na base
reingerida — A4 **15/18** (igual ao baseline), A2 7/7, A1 0, p95 **12,2 s**; suíte 279/14 e `ruff`
verdes. Registro em [`EVOLUCAO.md`](EVOLUCAO.md) §"Bloco 8".

---

## 6. Riscos e o que fazer se aparecerem

- **Concorrência no retrieval**: o preâmbulo é prosa didática e passa a competir com o dispositivo
  pelos 15 lugares do `TOP_K`. Hoje a recuperação usa 6,0–8,6 mil dos 12 mil caracteres de
  `MAX_CONTEXT_CHARS`, então há folga — mas se o A4 **cair**, a resposta é o **portão relativo
  (R-16)**, não reverter o R-24.
- **Reingestão silenciosa**: com `content_hash` por arquivo+nome+dono, a segunda carga é pulada pelo
  `ON CONFLICT` e a ingestão reporta **0 fragmentos** (P1-6). Apagar a fonte antes é obrigatório.
- **Fragmentos curtos**: a capa tem 88 caracteres e vira um fragmento pequeno; a regra do R-11 é
  descartar **só o vazio** (não por tamanho, porque `Art. 51. (Vetado).` tem 17 chars e é lei vigente)
  — mantida.
- **Preâmbulo da apostila ≠ preâmbulo do Planalto**: no texto oficial o pré-`Art. 1º` é o título e a
  ementa (curto e precioso); aqui são 25 páginas de material didático. A medição de cobertura vale
  para os dois, mas a leitura de qualidade só se confirma com o corpus oficial (P2-30).

## 7. Fora deste bloco (não mexo)

R-16 (portão relativo), R-18 (contexto por tokens), resposta extrativa, OCR (P2-19) e o corpus
oficial do Planalto (P2-30).
