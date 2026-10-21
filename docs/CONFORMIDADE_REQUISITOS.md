# Conformidade com os requisitos gerais

Avaliação do sistema contra o esboço de [`requisitos_gerais.txt`](requisitos_gerais.txt)
("o mínimo que o sistema deve fazer"), com o estado verificado por execução em **2026-10-20**.
Serve para não perder o rumo: cada requisito tem o que já existe, **onde está no código** e o que
falta — o que falta vira cartão no board (coluna indicada).

Legenda: ✅ atende · ⚠️ atende em parte · ❌ não atende.

| # | Requisito | Estado | O que existe hoje (evidência) | O que falta |
|:--|:---|:--:|:---|:---|
| 1 | Ingestão de PDF/DOCX com texto limpo | ⚠️ | **PDF** ✅ `PyPDFLoader` + `limpar_ruido_de_pagina` (remove cabeçalho/rodapé repetido e linha de página, preservando a linha que carrega identidade de norma) + `normalize_whitespace`; medido na apostila: 0 de 65 páginas fora do índice. **Texto** ✅ `.txt` com página sintética (ADR-0011). **DOCX** ❌ nenhum loader e nenhuma dependência (`python-docx`) no projeto | **P2-35** (DOCX). Tabelas dos anexos do Decreto 3.048 entram como texto corrido — aceitável para busca, ruim para extrair alíquota/teto em tabela |
| 2 | Terminologia jurídica específica (embeddings próprios + glossário) | ❌ | Usa `nomic-embed-text` genérico (`EMBEDDING_MODEL`) e não há glossário. O ganho de precisão veio por outro caminho, medido: identidade da norma no metadado (100 % dos fragmentos oficiais) e escopo por norma na busca (ADR-0012: norma pedida entre os 3 primeiros 4/7 → 7/7) | **P2-33** (apelido/nome por extenso por norma). Embedding próprio exige corpus rotulado — decisão de produto, não de código |
| 3 | Recuperação com citação exata da seção | ⚠️ | Cada trecho entra no contexto como `[DOC n]` com rótulo legível — `_source_label` monta "Lei 8.080, art. 19-Q" a partir de `tipo_doc`/`numero_doc`/`artigo`; o fact-check exige lastro da sentença **no fragmento citado** (ADR-0009), e `sem_lastro` bloqueia a exibição | Citação de **inciso/parágrafo** na resposta é texto do modelo, não garantia do sistema: o metadado tem `artigo`, `paragrafo` e `inciso`, mas o veredito é por sentença, não por dispositivo exato. **P2-39** |
| 4 | LGPD: local, sem vazamento | ⚠️ | Roda 100 % local: Ollama no host, Postgres em container, **nenhuma URL externa no código** (verificado por busca no `app/`). Isolamento por dono (`owner_id`) em documentos, fontes e recuperação (P0-3/P0-4 corrigidos) | **P0-5** (TLS + fechar a porta 5439) e **P0-6** (rotacionar credenciais) seguem abertos — dependem do cliente. Não há política de retenção/expurgo, base legal, consentimento registrado nem anonimização de dado pessoal em documento: **P2-37** |
| 5 | Validação de erro / confiança ("probabilidade < 80 %") | ⚠️ | A decisão de recusar é do **sistema**, não do modelo: portão de suficiência → lastro no fragmento citado → portão de exibição, com veredito (`fundamentada`/`parcial`/`recusou`/`sem_lastro`) e recusa canônica. Medido no corpus oficial: A1 (resposta com norma sem lastro) **0**, A2 (pergunta fora da base recusada) **7/7** | **Não existe probabilidade calibrada** — e ela não é confiável: as faixas de similaridade de pergunta atendida e não atendida **se sobrepõem** (medido: 0,761–0,829 contra 0,696–0,802). O equivalente funcional é o **portão relativo (R-16)** e o encaminhamento a revisão humana, que não existe |
| 6 | Controle de versão de documentos jurídicos | ❌ | Nada. `content_hash` é dedup de ingestão, não versão. Não há data de vigência nem histórico por fragmento. Mitigação parcial: o texto do Planalto é **compilado** (já consolidado), então não indexa redação revogada | **P2-36**: data de acesso/vigência por documento, `sha256` do fonte (o `corpus_planalto.py` já grava) e alerta quando o fonte muda |
| 7 | Explicabilidade das respostas | ⚠️ | Mostra as fontes numeradas e o veredito de lastro; quando recusa, diz o que faltou e quantos trechos viu (`_texto_recusa`) | Não explica **por que** a resposta foi gerada ("baseia-se no Art. 12 porque…"). O modelo pequeno (3,8 B) produz justificativa frágil — medir antes de prometer. **P2-39** |
| 8 | Testes com casos reais | ⚠️ | **301 casos unitários** em 14 módulos, 14 de integração contra Postgres real, `smoke_dev` ponta a ponta e dois medidores de produto (`medir_portao.py`, `medir_a4_repetido.py`) com 13 casos | Falta bateria de **casos reais com resposta-ouro por dispositivo**, validada por advogado; o mini-quiz atual é de dev e cobre só a Lei 8.080. **P2-38** |

## O que este mapa diz sobre prioridade

1. **O requisito 6 é o único totalmente ausente** e é o mais caro de improvisar depois: sem
   vigência, o produto pode responder com texto revogado sem saber. É dívida de arquitetura, não
   de feature.
2. **O requisito 5 já está meio resolvido de forma melhor que a pedida**: em vez de "probabilidade
   < 80 %" (que não separa nada, medido), o sistema recusa quando o contexto não sustenta. Falta o
   passo que o requisito pede de verdade: **revisão humana** e o portão relativo (R-16).
3. **O requisito 2 (embeddings próprios) é o de pior custo/benefício**: o que melhorou a precisão
   foi metadado e escopo por norma, não modelo. Antes de treinar embedding, medir o que o glossário
   resolveria.
4. **O requisito 1 tem uma lacuna barata** (DOCX) e uma cara (tabelas) — separar as duas evita
   prometer o que não se entrega.

## Rastreabilidade

Cada lacuna acima tem cartão no board `legaliz` (P2-35 a P2-39) e linha no
[`BACKLOG.md`](BACKLOG.md). Decisões de arquitetura relacionadas: [ADR-0009](adr/0009-portao-de-resposta-e-recusa-honesta.md)
(portão e recusa honesta), [ADR-0011](adr/0011-corpus-oficial-em-texto.md) (corpus oficial),
[ADR-0012](adr/0012-escopo-por-norma-e-teto-por-documento.md) (escopo por norma),
[ADR-0013](adr/0013-retirada-do-peso-por-regime.md) (peso por regime retirado).
