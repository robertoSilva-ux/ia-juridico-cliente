# Backlog — Legaliz.ai

Plano de ação derivado de [`docs/REVISAO_SEGURANCA.md`](REVISAO_SEGURANCA.md).
Prioridade: **P0** = bloqueia uso com dados reais de cliente · **P1** = alto ·
**P2** = melhoria/risco aceitável no curto prazo.

Legenda de status: ✅ feito · 🔄 em andamento · ⏳ aberto · 🅿️ decisão do cliente/produto

---

## P0 — antes de expor o sistema a dados reais

| ID | Item | Onde | Status | Critério de aceite |
|:---|:---|:---|:---|:---|
| P0-1 | Chave de assinatura do cookie vinda do ambiente, com validação de força | `app/config.py`, `app/main.py` | ✅ | App não sobe sem `COOKIE_KEY` de ≥32 bytes e não-pública; forja de cookie deixa de funcionar |
| P0-2 | Remover o admin semeado pelo schema e exigir `ADMIN_PASSWORD` | `database/init.sql`, `app/init_admin.py`, `setup.sh` | ✅ | Banco novo não tem usuário; `init_admin.py` falha com senha ausente/previsível |
| P0-3 | Escopo e exclusão de documento por dono (nunca por nome de arquivo) | `app/manage.py`, `app/main.py` | ✅ | Promover/excluir o arquivo de um dono não altera o homônimo de outro |
| P0-4 | Dedup e `sources` por `(file_name, owner_id)` | `app/ingest.py`, `app/scripts/backfill_sources.py`, `database/init.sql`, `database/migrate_sources_owner.sql` | ✅ | Upload do 2º dono com mesmo nome é indexado; fontes homônimas coexistem; **cargas sem dono (lote/legado) atualizam a fonte em vez de acumular linhas**; em banco existente, rodar `database/migrate_sources_owner.sql` (consolida duplicatas, reaponta os chunks e cria o índice `sources_file_owner_uidx`) |
| **P0-5** | **TLS e fechamento da rede** | `docker-compose.yml`, infra do cliente | ⏳ | HTTPS na frente do 8501 (certificado válido, redirect 80→443); `5439:5432` removido do host; firewall/security group restringindo às portas 443 (e 80) |
| **P0-6** | **Rotacionar as credenciais da instalação atual** | operação | ⏳ | `COOKIE_KEY` nova gerada; senha do admin do cliente trocada; `POSTGRES_PASSWORD` real (não o placeholder) — trocar exige recriar o volume do banco ou `ALTER USER` |

> P0-6 é operacional, não de código: as chaves que já circularam em texto claro
> (banco na 5439, HTTP no 8501) precisam ser tratadas como comprometidas.

---

## P1 — alto

| ID | Item | Onde | Status | Critério de aceite |
|:---|:---|:---|:---|:---|
| **P1-1** | Fact-check não pode carregar a base inteira nem validar contra outros clientes | `app/factcheck.py` | ✅ | `_load_dispositivos_base(user_id)` filtra por escopo (`scope='global' OR owner_id=%s`, legado `owner_id IS NULL`); cache **por dono** com limite de linhas/caracteres (`FACT_CHECK_CACHE_MAX_ROWS=20000`, `FACT_CHECK_CACHE_MAX_CHARS=8000000`); `user_id` encadeado por `_check_semantic_grounding`/`_fact_check_answer`/`agent`. Medido: dono B não recebe mais dispositivo do dono A |
| **P1-2** | Remover estado global de LLM entre sessões | `app/agent.py`, `app/main.py` | ⏳ | Troca de modelo afeta apenas a sessão que trocou; `stop_model`/`pull_model` restritos ao admin (`is_ollama_connected` continua livre) |
| **P1-3** | Todo o `.env` chega ao container | `docker-compose.yml` | ✅ | `env_file: - .env` no serviço `app`; ajustar `HYDE_*`/`RERANK_*`/`FACT_CHECK_*` no `.env` muda o comportamento |
| **P1-4** | Pins de dependências e imports declarados | `app/requirements.txt`, `app/requirements.lock.txt` | ✅ | Build reproduzível; `requests`, `langchain-core`, `langchain-text-splitters` declarados; lock instalável (`pip install --dry-run`) |
| **P1-5** | CI roda lint + testes + integração + schema | `.github/workflows/ci.yml`, `app/run_tests.sh`, `Makefile` | ✅ | `make test` passa; CI verde cobre os 12 módulos; job de schema aplica `init.sql` 2× |
| **P1-6** | Falha explícita em PDF sem texto extraível | `app/ingest.py`, `app/main.py` | ✅ | Ingestão com 0 fragmentos devolve aviso ao usuário ("pode ser digitalizado **ou** os fragmentos já estavam na base"), nunca "indexado com sucesso" — `ui_feedback.render_indexacao_pdf` + 3 testes. OCR em si segue em P2-19 |
| **P1-7** | Gate de ACL no compose: confirmar que só o app alcança o banco | `docker-compose.yml` | ⏳ | Banco sem `ports:`; comunicação só pela rede interna do compose |
| **P1-8** | Prompt injection indireta via documento indexado | `app/prompts/system-role.md`, `app/agent.py` | ⏳ | O system prompt instrui explicitamente que o conteúdo dos `[DOC n]` é **dado**, não instrução, e que pedidos vindos dele devem ser ignorados/relatados; teste com um chunk contendo "ignore as instruções acima" não altera o comportamento |
| **P1-9** | Fact-check marca resposta **correta** como "parcial" (falso positivo) | `app/factcheck.py` | 🔄 reduzido | Dispositivo comparado com `_normalize_dispositivo` dos dois lados ("artigo 25" casa com "Art. 25.") e frase sem afirmação factual não vira `partial`; testes de regressão com o caso reproduzido no `scripts/smoke_dev.py`. **Fase 1 (bloco 6):** a causa dominante caiu — a seção obrigatória "ARBITRAGEM DE REGIME JURÍDICO" saiu do prompt e resposta sem unidade verificável (`sem_fonte`) passou a ser **aviso**, não bloqueio. Falta o resto do item (formato de dispositivo). |
| **P1-10** | **Falha de GPU derruba o produto, e a interface esconde a causa** (medido em 2026-10-16 na RTX 3050 de 6 GB): (a) o desktop ocupa ~0,8 GB, deixando **5.060 MiB livres** — modelos ≥4,7 GB não cabem com o embeddings e o KV cache, o Ollama joga camadas na CPU e a resposta leva 100–200 s (`ollama ps` mostrando `100% CPU`); (b) durante os testes a placa **caiu do barramento PCIe** — `nvidia 0000:03:00.0: AER: can't recover`, repetido por ~1 h, com `CUDA error: unspecified launch failure` e `llama-server GPU discovery watchdog timed out`; (c) nesse estado o usuário recebe **"Erro interno ao processar a consulta."** sem fontes e sem fact-check, sem nenhuma pista de que é hardware. Erro de infraestrutura indo para o cliente como bug de produto | `app/agent.py`, `docker-compose.yml`, `app/ollama_utils.py`, README | ⏳ | Modelo/contexto escolhidos pelo orçamento de VRAM **medido** (2,5–3,5 GB cabem; 4,0 GB é limítrofe; ≥4,7 GB não cabe com desktop); a interface distingue "sem memória/GPU indisponível" de erro interno e diz o que fazer; README e ensaio de paridade trazem o requisito de VRAM (servidor **headless** tem ~5,8 GB livres, sem os 0,8 GB do desktop) |

---

## P2 — melhorias e riscos residuais

### Segurança e acesso
| ID | Item | Onde | Status |
|:---|:---|:---|:---|
| P2-1 | Rate limiting / lockout no login (proteção a força bruta) | `app/main.py` | ⏳ |
| P2-2 | `update_password()` validar a nova senha como `add_user()` faz | `app/auth.py` | ⏳ |
| P2-3 | Fluxo de exclusão de usuário (hoje não existe) + revogação de sessão | `app/auth.py`, painel | ⏳ |
| P2-4 | Log de ações administrativas (mudança de escopo, exclusão, reset de senha) | `app/audit.py` | ⏳ |
| P2-5 | Política de retenção/anonimização do `audit_log` (LGPD, segredo de justiça) | `app/audit.py` | 🅿️ |
| P2-6 | Revisar se as 0.4.x da `streamlit-authenticator` mantêm a API usada; considerar autenticação própria/OIDC | `app/main.py` | 🅿️ |
| P2-7 | Decidir sobre o repositório público (código do produto entregue a cliente) | GitHub | 🅿️ |

### Banco e infraestrutura
| ID | Item | Onde | Status |
|:---|:---|:---|:---|
| P2-8 | Migrar de `ankane/pgvector` (não oficial) para `pgvector/pgvector` | `docker-compose.yml` | ⏳ |
| P2-9 | `runtime: nvidia` incondicional quebra host sem GPU (o setup prevê CPU) | `docker-compose.yml` | ⏳ |
| P2-10 | Caminhos absolutos `/srv/ia-juridico` (compose) vs `/opt/ia-juridico` (setup) → parametrizar | `docker-compose.yml`, `setup.sh` | ⏳ |
| P2-11 | Backup automatizado do volume do Postgres + teste de restauração | `setup.sh`, cron | ⏳ |
| P2-12 | Usar o pool de `database.py` em `manage.py`/`audit.py`/`auth.py`/`ingest.py` (hoje abrem `psycopg2.connect` direto, ignorando `DB_POOL_*`) | vários | ⏳ |
| P2-13 | Aumentar `mem_limit` do `app` ou reduzir o cache do fact-check (512 MB é apertado) | `docker-compose.yml` | ⏳ |
| P2-14 | `IVFFLAT_PROBES`/`lists=100` revisados com a base real do cliente | `database/init.sql`, `config.py` | ⏳ |

### Código e dados
| ID | Item | Onde | Status |
|:---|:---|:---|:---|
| P2-15 | Tornar o isolamento obrigatório: `user_id` sem default `None` nos caminhos de chat | `app/agent.py`, `app/regime.py` | ⏳ |
| P2-16 | `UNIQUE (file_name, owner_id, md5(content))` em `documents` (hoje o dedup é só de aplicação) | `database/init.sql`, `database/migrate_documents_hash.sql`, `app/ingest.py` | ✅ | Coluna `content_hash` (md5) + índice único `documents_file_owner_hash_uidx`; a ingestão grava com `ON CONFLICT (file_name, (COALESCE(owner_id, -1)), content_hash) DO NOTHING` e conta o que o banco inseriu (`rowcount`). Verificado em Postgres real: duplicata direta rejeitada, `ON CONFLICT` sem erro, mesmo conteúdo de outro dono entra. Em base existente: `database/migrate_documents_hash.sql` |
| P2-17 | Remover `python-dotenv` (declarado, nunca importado) | `app/requirements.txt` | ⏳ |
| P2-18 | `ENCRYPTION_KEY` documentada e sem uso — implementar ou remover da doc/`.env.example` | `config`, README | ⏳ |
| P2-19 | Extração de texto com OCR para PDFs digitalizados (P1-6 é o alerta; isto é a solução) | `app/ingest.py` | 🅿️ |
| P2-20 | `LLM_NUM_CTX` × `MAX_CONTEXT_CHARS` × histórico: hoje nada conta tokens (o Ollama trunca em silêncio) | `app/agent.py`, `app/ranking.py` | ⏳ |
| P2-25 | `st.components.v1.html` (usado em `main.py` para forçar `lang=pt-br`) está **além da data de remoção** anunciada pela própria lib ("will be removed after 2026-06-01"); com o Streamlit pinado (1.66.0) funciona, mas o próximo bump pode quebrar a página | `app/main.py` | ⏳ |
| P2-26 | Rótulos da resposta com erro de escrita pelo modelo pequeno (`"OBRJETO"` em vez de `OBJETO`, reproduzido no smoke) junto com os 3 "parcial" do P1-9 — o formato vem do prompt e o `phi4-mini:3.8b` não o cumpre de forma confiável: decidir entre modelo maior, validação de formato na saída ou pós-processamento dos rótulos | `app/agent.py`, `app/prompts/`, `app/config.py` | ⏳ |
| P2-27 | `database.py` monta o pool **no import**, então um `DATABASE_URL` inalcançável vira traceback antes de qualquer linha de UI (visto ao montar uma página de prévia). Pior no Streamlit: `config` fica cacheado no `sys.modules` entre reruns, então um DSN ruim lido no primeiro run sobrevive ao ambiente corrigido — o processo precisa nascer com o ambiente certo. Criar o pool sob demanda e falhar com mensagem clara | `app/database.py`, `app/config.py` | ⏳ |
| P2-28 | Fila de upload de **múltiplos** arquivos com progresso por arquivo e resumo final (a interface que existia antes da limpeza do repositório, em `def535b`, e que não está em nenhum commit daqui). Hoje: um arquivo por vez — decisão do usuário em 2026-10-16 (fazer o mínimo primeiro). O componente já aceita ser chamado em laço (`render_indexacao_pdf`) | `app/main.py`, `app/ui_feedback.py` | 🅿️ |
| P2-29 | Cabeçalho/rodapé **repetido dentro de cada fragmento** quando o PDF de origem é apostila (medido: `Prof. Adriano de Oliveira www.estrategiaconcursos.com.br 48 de 64` no meio do texto de todos os chunks da Lei 8.080). Polui o embedding, come contexto e é justamente "texto que não é lei". Remover linhas que se repetem entre páginas na ingestão | `app/ingest.py` | ✅ | `limpar_ruido_de_pagina` roda na extração, antes do split: compara linhas com os **números normalizados** (`… 25 de 64` = `… 26 de 64`), remove o que se repete em ≥50% das páginas (mín. 3), tira linha que é só número de página e **preserva** a linha que carrega identidade de norma/dispositivo — no texto oficial do Planalto ela se repete em toda página e é o que dá o par número+ano a cada fragmento |
| P2-30 | **Corpus precisa ser fonte oficial, não material didático.** O material indexado é uma apostila ("esquematizada"): o número da lei aparece em 1 fragmento de 119 e a data em outro, então nem o modelo nem o fact-check têm como verificar a identificação da norma. Em texto do Planalto ("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990" no cabeçalho de toda página) o par número+ano vem junto em cada fragmento. Recomendação para a operação do cliente — não é mudança de código | operação/corpus | 🔄 | **Lado do código pronto** (R-9 lê a identidade do conteúdo; R-10/R-11 limpam o ruído sem apagar a linha de identidade repetida, que é justamente o ganho do texto oficial). **Falta a operação**: trazer o texto oficial e reingerir — é o bloco pendente de autorização (corpus a definir) |
| P2-31 | `factcheck._load_dispositivos_base` varre o `content` de **todos** os trechos por padrão de dispositivo, sem filtrar `tipo_trecho` — em tese um artigo citado só em comentário/prâmbulo passa a "existir" na base como dispositivo (o plano do R-24 previa o filtro e ele não entrou). Medido na base de dev em 2026-10-19: **efeito zero** (60 dispositivos vindos de fragmento `dispositivo`, 60 no total). Revisitar com o corpus oficial, onde comentário é mais numeroso | `app/factcheck.py` | ⏳ |

### Documentação (divergências encontradas)
| ID | Item | Status |
|:---|:---|:---|
| P2-21 | README: `SIMILARITY_THRESHOLD` padrão, "cryptography no requirements", `env_file`, `init.sql` sem dados, roadmap de isolamento | ✅ corrigido |
| P2-22 | `docs/AGENTS.md` descrevia o isolamento por `user_id` como "Próxima Fase" (já implementado) | ✅ corrigido |
| P2-23 | `docs/TESTING.md` listava achados já resolvidos (ordem do `init.sql`, erro no `test_auth`) e o runner antigo | ✅ corrigido |
| P2-24 | `docs/TASKS.md`: contagem de testes e status da task de escopo por usuário | ✅ corrigido |

---

## Ordem de execução sugerida

0. **Refinamento do RAG (fundamentação e recusa honesta)** — plano detalhado, com evidência
   medida: [`docs/PLANO_REFINAMENTO_RAG.md`](PLANO_REFINAMENTO_RAG.md) (itens R-1 a R-25;
   **Fases 1 e 2 executadas, incluindo R-24/R-25** — [ADR-0010](adr/0010-preambulo-e-conteudo-indexavel.md)).
   É o que atende ao pedido "resposta 100 % fundamentada ou dizer que não encontrou". Próximo:
   **Fase 3** (R-15, R-16, R-18), que depende do corpus oficial.
1. **P0-5 + P0-6** (TLS, fechar a rede, rotacionar credenciais) — é o que falta para o
   sistema poder receber dados reais. **Só o cliente executa.**
2. **P1-1** (fact-check) — ✅ **feito** (bloco 7).
3. **P2-30** (corpus oficial do Planalto) — ✅ **R-24/R-25 feitos** (bloco 8: preâmbulo indexado,
   92.037 → 94.563 chars, 0 de 65 páginas fora do índice, A4 15/18 mantido). O que resta é o
   corpus: é o que dá o que calibrar em **R-16** e mede o A4 de novo, e é pré-requisito da
   Fase 3.
4. **P1-2** e **P1-6** — interferência entre sessões e falha silenciosa de ingestão.
5. **P1-7**, depois P2-8/P2-9/P2-10/P2-11 (infra reproduzível + backup).
6. P2 em ondas, começando por P2-1, P2-2, P2-4, P2-12.
