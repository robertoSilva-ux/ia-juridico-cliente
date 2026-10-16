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
| P0-4 | Dedup e `sources` por `(file_name, owner_id)` | `app/ingest.py`, `app/scripts/backfill_sources.py`, `database/init.sql` | ✅ | Upload do 2º dono com mesmo nome é indexado; fontes homônimas coexistem |
| **P0-5** | **TLS e fechamento da rede** | `docker-compose.yml`, infra do cliente | ⏳ | HTTPS na frente do 8501 (certificado válido, redirect 80→443); `5439:5432` removido do host; firewall/security group restringindo às portas 443 (e 80) |
| **P0-6** | **Rotacionar as credenciais da instalação atual** | operação | ⏳ | `COOKIE_KEY` nova gerada; senha do admin do cliente trocada; `POSTGRES_PASSWORD` real (não o placeholder) — trocar exige recriar o volume do banco ou `ALTER USER` |

> P0-6 é operacional, não de código: as chaves que já circularam em texto claro
> (banco na 5439, HTTP no 8501) precisam ser tratadas como comprometidas.

---

## P1 — alto

| ID | Item | Onde | Status | Critério de aceite |
|:---|:---|:---|:---|:---|
| **P1-1** | Fact-check não pode carregar a base inteira nem validar contra outros clientes | `app/factcheck.py` | ⏳ | `_load_dispositivos_base` recebe `user_id` e filtra por escopo (`scope='global' OR owner_id=%s`); cache com limite de linhas/caracteres ou por dono; invalidado na ingestão |
| **P1-2** | Remover estado global de LLM entre sessões | `app/agent.py`, `app/main.py` | ⏳ | Troca de modelo afeta apenas a sessão que trocou; `stop_model`/`pull_model` restritos ao admin (`is_ollama_connected` continua livre) |
| **P1-3** | Todo o `.env` chega ao container | `docker-compose.yml` | ✅ | `env_file: - .env` no serviço `app`; ajustar `HYDE_*`/`RERANK_*`/`FACT_CHECK_*` no `.env` muda o comportamento |
| **P1-4** | Pins de dependências e imports declarados | `app/requirements.txt`, `app/requirements.lock.txt` | ✅ | Build reproduzível; `requests`, `langchain-core`, `langchain-text-splitters` declarados; lock instalável (`pip install --dry-run`) |
| **P1-5** | CI roda lint + testes + integração + schema | `.github/workflows/ci.yml`, `app/run_tests.sh`, `Makefile` | ✅ | `make test` passa; CI verde cobre os 12 módulos; job de schema aplica `init.sql` 2× |
| **P1-6** | Falha explícita em PDF sem texto extraível | `app/ingest.py`, `app/main.py` | ⏳ | Ingestão sem chunks válidos retorna erro/aviso ao usuário ("PDF sem texto — pode ser digitalizado"), nunca "indexado com sucesso" |
| **P1-7** | Gate de ACL no compose: confirmar que só o app alcança o banco | `docker-compose.yml` | ⏳ | Banco sem `ports:`; comunicação só pela rede interna do compose |
| **P1-8** | Prompt injection indireta via documento indexado | `app/prompts/system-role.md`, `app/agent.py` | ⏳ | O system prompt instrui explicitamente que o conteúdo dos `[DOC n]` é **dado**, não instrução, e que pedidos vindos dele devem ser ignorados/relatados; teste com um chunk contendo "ignore as instruções acima" não altera o comportamento |

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
| P2-16 | `UNIQUE (file_name, owner_id, md5(content))` em `documents` (hoje o dedup é só de aplicação) | `database/init.sql` | ⏳ |
| P2-17 | Remover `python-dotenv` (declarado, nunca importado) | `app/requirements.txt` | ⏳ |
| P2-18 | `ENCRYPTION_KEY` documentada e sem uso — implementar ou remover da doc/`.env.example` | `config`, README | ⏳ |
| P2-19 | Extração de texto com OCR para PDFs digitalizados (P1-6 é o alerta; isto é a solução) | `app/ingest.py` | 🅿️ |
| P2-20 | `LLM_NUM_CTX` × `MAX_CONTEXT_CHARS` × histórico: hoje nada conta tokens (o Ollama trunca em silêncio) | `app/agent.py`, `app/ranking.py` | ⏳ |

### Documentação (divergências encontradas)
| ID | Item | Status |
|:---|:---|:---|
| P2-21 | README: `SIMILARITY_THRESHOLD` padrão, "cryptography no requirements", `env_file`, `init.sql` sem dados, roadmap de isolamento | ✅ corrigido |
| P2-22 | `docs/AGENTS.md` descrevia o isolamento por `user_id` como "Próxima Fase" (já implementado) | ✅ corrigido |
| P2-23 | `docs/TESTING.md` listava achados já resolvidos (ordem do `init.sql`, erro no `test_auth`) e o runner antigo | ✅ corrigido |
| P2-24 | `docs/TASKS.md`: contagem de testes e status da task de escopo por usuário | ✅ corrigido |

---

## Ordem de execução sugerida

1. **P0-5 + P0-6** (TLS, fechar a rede, rotacionar credenciais) — é o que falta para o
   sistema poder receber dados reais.
2. **P1-1** (fact-check) — é o mais próximo de um incidente de produção (OOM e validação
   cruzada entre clientes).
3. **P1-2** e **P1-6** — interferência entre sessões e falha silenciosa de ingestão.
4. **P1-7**, depois P2-8/P2-9/P2-10/P2-11 (infra reproduzível + backup).
5. P2 em ondas, começando por P2-1, P2-2, P2-4, P2-12.
