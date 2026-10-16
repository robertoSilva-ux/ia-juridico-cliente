# Revisão de Segurança e Isolamento entre Clientes — Legaliz.ai

| | |
|:---|:---|
| **Escopo** | Repositório inteiro (`app/`, `database/`, `docker-compose.yml`, `setup.sh`, CI, docs) |
| **Commit analisado** | `f613ad1` (branch `main`, último push 2026-10-06) |
| **Data da revisão** | 2026-10-16 |
| **Tamanho** | ~4.850 linhas de Python de aplicação + ~1.810 de testes |
| **Natureza** | Produto entregue a cliente; base documental jurídica, possível segredo de justiça |

Este documento registra o que foi encontrado, **como cada achado foi verificado**, o que
foi corrigido e o que segue pendente. O plano de ação está em
[`docs/BACKLOG.md`](BACKLOG.md).

---

## Resumo executivo

O produto tem uma base de engenharia acima da média (pipeline de RAG com HyDE/RRF/MMR,
fact-check determinístico, prompts separados, avaliador reproduzível, 158 casos de teste).
O que faltava era a camada de **autenticação e de isolamento entre clientes** — e era ali
que estavam os problemas graves.

| # | Achado | Gravidade | Status |
|:--|:---|:---|:---|
| **P0-1** | Bypass total de autenticação: a chave que assina o cookie de sessão era o literal `legal_ai_key`, num repositório **público** | Crítica | ✅ corrigido |
| **P0-2** | Schema do banco semeava `admin@legaliz.ai` / `admin123` (hash fixo no `init.sql`) | Crítica | ✅ corrigido |
| **P0-3** | "Tornar Global" agia por nome de arquivo e promovia junto o documento privado homônimo de **todos** os outros usuários | Crítica | ✅ corrigido |
| **P0-4** | Dedup de ingestão era por nome de arquivo: o upload do 2º usuário com o mesmo nome era 100% descartado (e a UI dizia "sucesso"), além de a linha de `sources` trocar de dono | Alta | ✅ corrigido |
| **P0-5** | Sem TLS no Streamlit (0.0.0.0) e porta do PostgreSQL publicada no host | Alta | ⏳ pendente |
| **P1-1** | Fact-check carregava a base inteira (todos os clientes) em memória, num container de 512 MB | Alta | ⏳ pendente |
| **P1-2** | Estado global de LLM compartilhado entre sessões (qualquer usuário troca o modelo / baixa modelos) | Média | ⏳ pendente |
| **P1-3** | Metade do `.env` era ignorada pelo `docker-compose` (sem `env_file`) | Média | ✅ corrigido |
| **P1-4** | Dependências sem versão fixa (`requirements.txt`); `requests`/`langchain-core`/`langchain-text-splitters` usados e não declarados | Média | ✅ corrigido |
| **P1-5** | CI não rodava teste nenhum (só flake8); `make test` apontava para arquivos inexistentes; 5 dos 9 módulos de teste nunca eram executados | Alta | ✅ corrigido |
| **P1-6** | PDF escaneado (sem texto) resultava em no-op silencioso com mensagem de sucesso | Média | ⏳ pendente |
| **P2-*** | 10 achados menores (backups, chaves duplicadas do Streamlit, validação de senha no reset, imagem de banco não oficial, LGPD do `audit_log`, docs divergentes…) | Baixa/Média | parcialmente corrigido |

---

## Como esta revisão foi verificada

Nada aqui é conclusão de leitura de código apenas. O que foi executado:

| Verificação | Ferramenta | Resultado |
|:---|:---|:---|
| Senha do admin semeado pelo `init.sql` | `bcrypt.checkpw` | `True` para `admin123` |
| Forja do cookie de sessão com a chave do repositório | `pyjwt` + código-fonte da lib | assinatura **aceita** pela própria `streamlit-authenticator` |
| Segredos reais no histórico do git | varredura de todo o histórico | **nenhum** (só placeholders) |
| Semântica do `UPDATE` de escopo e do dedup | PostgreSQL 16.2 real (binário local) | vazamento e descarte **reproduzidos** |
| Correções de SQL (índice único, `ON CONFLICT`, escopo por dono) | PostgreSQL 16.2 real com pgvector | `init.sql` aplicado 2× + 10 testes de integração verdes |
| Suíte de testes | Python 3.11.17 + dependências reais | 158 casos, 12 módulos, **todos verdes** |

Limitação registrada no fim do documento: não havia Docker nesta máquina, então o
`docker compose`, o Streamlit e o Ollama **não** foram exercitados ponta a ponta.

---

## P0 — bloqueadores para uso com dados reais de cliente

### P0-1 · Bypass de autenticação pela chave do cookie ✅

**O que era.** Em `app/main.py`:

```python
authenticator = stauth.Authenticate(
    credentials, "legal_ai_cookie", "legal_ai_key", cookie_expiry_days=30
)
```

O terceiro argumento é a **chave de assinatura** do cookie de sessão. Na
`streamlit-authenticator`, ela é usada literalmente como segredo HMAC:

```python
# streamlit_authenticator/models/cookie_model.py
jwt.encode({'username': st.session_state['username'], 'exp_date': self.exp_date},
           self.cookie_key, algorithm='HS256')
jwt.decode(self.token, self.cookie_key, algorithms=['HS256'])
```

E o `get_cookie()` aceita o token apenas verificando a assinatura, a presença de
`username` e a data de expiração. Como o valor `legal_ai_key` estava **versionado num
repositório público**, qualquer pessoa que alcançasse a porta 8501 gerava um cookie
válido para `admin@legaliz.ai` e entrava como administrador **sem senha**.

**Evidência (executada).** Assinatura de um JWT com a chave pública do repositório e
decodificação pela própria biblioteca: aceita, com aviso `InsecureKeyLengthWarning`
(chave de 12 bytes; o mínimo recomendado é 32 — RFC 7518 §3.2).

**Correção aplicada.** A chave passou a vir do ambiente (`COOKIE_KEY`), sem valor padrão,
com portão de qualidade em `app/config.py::cookie_key_problem()`:

* ausente → recusa;
* valor conhecido/público (`legal_ai_key`, `some_key`, `changeme`…) → recusa;
* menos de 32 bytes → recusa;
* em qualquer desses casos `main.py` **para a aplicação antes de tocar no banco**.

Cobertura: `app/tests/test_config_cookie.py` (9 casos, incluindo contagem em bytes).

> ⚠️ Ao aplicar em produção: gerar uma chave por instalação
> (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`) e lembrar que trocá-la
> invalida as sessões ativas (todos refazem login).

### P0-2 · Credencial de administrador conhecida no schema ✅

**O que era.** O bloco "Dados iniciais" de `database/init.sql` inseria o admin com um
hash bcrypt fixo. Confirmado por execução: o hash corresponde a **`admin123`**. E o
`setup.sh` imprimia `👤 Login: admin@legaliz.ai / admin123` no fim do setup. Ou seja:
todo banco novo nascia com credencial de administrador adivinhável — e o README afirmava
o contrário ("`init.sql` limpo: apenas schema, sem dados hardcoded").

**Correção aplicada.**

* `database/init.sql` não semeia mais nenhum usuário (com nota de migração para bases
  antigas);
* `app/init_admin.py` **falha** (exit code 1) quando `ADMIN_PASSWORD` está ausente, é
  curta (< 8) ou é um valor previsível (`admin123`, `admin`, `password`…);
* `setup.sh` valida `POSTGRES_PASSWORD`, `ADMIN_PASSWORD` e `COOKIE_KEY` **antes** de
  subir os containers e falha se ainda estiverem com o placeholder do template;
* a mensagem final do setup não imprime mais credenciais.

Cobertura: `app/tests/test_init_admin.py` (9 casos; garante que a senha em claro nunca
chega ao SQL e que rodar de novo não reseta a senha de quem já existe).

### P0-3 · Escopo de documento era por nome de arquivo (vazamento entre clientes) ✅

**O que era.** `app/manage.py`:

```python
cur.execute("UPDATE documents SET scope = %s WHERE file_name = %s", (new_scope, file_name))
```

`file_name` é único **por acaso**, nunca por construção: nomes como `peticao.pdf`,
`contrato.pdf` e `decreto.pdf` se repetem entre usuários. Um clique em "🌐 Tornar Global"
(o botão existe no painel do admin) promovia, junto com o arquivo alvo, **o arquivo
privado homônimo de todos os outros usuários** — e o filtro de recuperação do chat
(`scope = 'global' OR owner_id = %s`) passava a devolvê-lo para toda a base. O mesmo valia
para a exclusão: `delete_document` do admin apagava `WHERE file_name = %s`, ou seja, o
arquivo privado de todo mundo com aquele nome.

**Evidência (executada).** Em PostgreSQL real: dois donos com `peticao.pdf` privado;
uma única ação de um deles levou as **duas** linhas a `global` (a segunda pertencia ao
outro usuário). Reprodução também em SQL isolado, com o mesmo resultado.

**Correção aplicada.**

* `_resolve_target_owner()` centraliza a regra: usuário comum age só sobre os próprios
  documentos; admin age sobre **um dono por vez**, informado explicitamente;
* `update_document_scope()` e `delete_document()` filtram por `owner_id` e **exigem
  `user_id`** (sem ele, falham em vez de varrer a base);
* `list_documents()` agrupa e devolve `(arquivo, data, chunks, escopo, owner_id, email)`,
  então o painel distingue arquivos homônimos e exibe de quem são;
* `update_document_scope()` sincroniza `sources.scope` na mesma transação — antes as duas
  tabelas podiam discordar sobre o que é público;
* escopo inválido é recusado por allowlist antes de tocar o banco.

Cobertura: 7 casos unitários (`test_management.py`) + 10 de integração
(`test_integration_tenancy.py`), incluindo o cenário exato acima.

### P0-4 · Dedup e `sources` atravessavam donos ✅

**O que era.** `app/ingest.py` deduplicava por nome de arquivo
(`SELECT content FROM documents WHERE file_name = %s`), mas insere com o `owner_id` de
quem subiu. Consequência: se o cliente A já tinha `contrato.pdf`, o upload do cliente B
com o mesmo nome era **integralmente filtrado** — nenhuma linha era gravada para B, a
recuperação de B não achava nada e a interface mostrava
`Documento 'contrato.pdf' indexado com sucesso!`.

E o upsert da tabela `sources` (`UNIQUE (file_name)`, com
`owner_id = COALESCE(EXCLUDED.owner_id, sources.owner_id)`) **reescrevia o dono da fonte
existente**: metadado de um cliente passando a pertencer a outro.

**Evidência (executada).** PostgreSQL real: a consulta de dedup do 2º dono devolvia os
chunks do 1º; o `ON CONFLICT (file_name)` sobrescrevia `owner_id` da fonte alheia.
Reproduzido também em SQL isolado.

**Correção aplicada.**

* dedup por `(file_name, owner_id IS NOT DISTINCT FROM %s)` — preservando o comportamento
  para chunks legados com dono nulo;
* `sources` passa a ter índice único em **`(file_name, owner_id)`** (`database/init.sql`
  migra bases existentes de forma idempotente);
* upsert com `ON CONFLICT (file_name, owner_id)` e sem reescrever o dono;
* o mesmo tratamento no script de backfill (`app/scripts/backfill_sources.py`) e no schema
  de teste (`docs/legal_test_schema.sql`) — a correção foi feita na classe do problema,
  não em um só ponto.

Cobertura: 5 casos unitários + 3 de integração (chunks do 2º dono indexados, fontes
homônimas coexistindo, reindexação do mesmo dono continuando deduplicada).

### P0-5 · Falta de TLS e porta do banco publicada ⏳ pendente

`docker-compose.yml` publica `8501:8501` (Streamlit em HTTP puro, `--server.address=0.0.0.0`
no Dockerfile) e `5439:5432` (PostgreSQL acessível de fora da rede Docker). Não há proxy
reverso nem TLS. Num produto jurídico isso significa senha de login e conteúdo de peças
trafegando em claro na rede do cliente, e o banco exposto a quem alcançar a porta.

Encaminhamento (ver BACKLOG): TLS via reverse proxy na frente do 8501, remover o
mapeamento do banco para o host e restringir por firewall/rede interna.

---

## P1 — alto

### P1-1 · Fact-check carrega a base inteira, de todos os clientes ⏳

`app/factcheck.py::_load_dispositivos_base()` executa
`SELECT content FROM documents WHERE content IS NOT NULL` — sem filtro de dono — e
mantém o resultado num cache global. Três problemas: (a) o container `app` tem
`mem_limit: 512m` e a primeira pergunta de cada sessão materializa o corpus inteiro em
memória; (b) a validação de "dispositivo inventado" passa a ser feita contra documentos
de **outros clientes**, então um artigo que não existe na base do cliente B pode passar
porque existe na do A; (c) o cache só é invalidado manualmente.

### P1-2 · Estado global de LLM compartilhado entre sessões ⏳

`app/agent.py` mantém `LLM`/`CHAIN` como globais do módulo e
`set_llm_model()` (chamado pela sidebar, disponível para **qualquer** usuário
autenticado) troca o modelo de **todas** as sessões, além de chamar `stop_model()` nos
outros modelos carregados. A mesma sidebar permite baixar modelos arbitrários do Ollama
(consumo de disco/rede do cliente).

### P1-3 · Configuração ignorada em silêncio ✅

O serviço `app` do `docker-compose.yml` não tinha `env_file` e repassava só 9 variáveis
por uma lista explícita. Ajustes legítimos do cliente em `MAX_CONTEXT_CHARS`, `RERANK_*`,
`HYDE_*`, `FACT_CHECK_*`, `DB_POOL_*`, `IVFFLAT_PROBES`, `EMBED_BATCH_SIZE`, `COOKIE_KEY`
e `ADMIN_*` eram **silenciosamente ignorados** (e o README afirmava que havia
`env_file: .env`). Corrigido com `env_file: - .env`.

### P1-4 · Dependências sem pin e imports não declarados ✅

`app/requirements.txt` não fixava versão nenhuma — um rebuild no servidor do cliente
resolveria pacotes novos sem mudança de código (a `streamlit-authenticator` mudou de API
entre as séries 0.3 e 0.4, e é ela que assina o cookie). Além disso, `requests`
(usado em `ollama_utils.py`), `langchain-core` (agent/main) e `langchain-text-splitters`
(ingest) eram importados e não declarados; `pytest` era usado pelo Makefile sem estar
instalado. Corrigido: pins validados em Python 3.11 + `requirements.lock.txt` com a
resolução completa + dependências faltantes declaradas + `make test` usando o runner
`unittest` do próprio projeto (não é preciso `pytest`).

### P1-5 · A verificação automatizada não verificava nada ✅

* CI rodava **só** flake8 `--select=E9,F63,F7,F82`, nunca a suíte — e flake8, não o ruff
  configurado no `pyproject.toml`;
* `make test` chamava `pytest test_auth.py test_management.py` a partir de `app/`, mas os
  arquivos vivem em `app/tests/` — o alvo simplesmente não existia;
* o `scripts/run_tests.sh` tinha lista fixa de 4 módulos: **5 dos 9 arquivos de teste
  nunca eram executados por ninguém** (incluindo o `test_agent.py`, o maior da suíte).

Corrigido: runner único em `app/run_tests.sh` (descoberta dinâmica, um módulo por
processo, total de casos no resumo), `make test`/`make test-local`, CI com lint (ruff) +
testes + **integração contra Postgres pgvector** + um job que aplica o `database/init.sql`
duas vezes e confere as invariantes de segurança do schema.

### P1-6 · PDF escaneado falha em silêncio ⏳

Não há OCR. Quando o `PyPDFLoader` não extrai texto, `store_in_postgres` retorna sem
gravar nada e a interface ainda exibe "indexado com sucesso". Em fluxo jurídico, PDF
escaneado é o caso comum.

---

## P2 — médio/baixo

| Achado | Onde | Status |
|:---|:---|:---|
| `.env.cliente` versionado com `POSTGRES_PASSWORD` e `DATABASE_URL` **inconsistentes** (mesmo em placeholders, o app não conectaria) | `.env.cliente` | ✅ corrigido (placeholders coerentes + validação no `setup.sh`) |
| Admin deletando "documentos sem nome" apagava órfãos de qualquer dono (`DELETE ... WHERE file_name IS NULL`) | `manage.py` | ✅ corrigido (restrito a `owner_id IS NULL`) |
| Chaves de widget do Streamlit só pelo nome do arquivo → arquivo homônimo de dois donos quebra a página | `main.py` | ✅ corrigido (chave inclui o dono) |
| `update_password()` (reset pelo admin) não validava nada, diferente de `add_user()` | `auth.py` | ⏳ pendente |
| `ENCRYPTION_KEY` documentada (README e `.env.example`) e **sem uso** no código; `cryptography` não instalado | `config`/README | ⏳ pendente |
| `python-dotenv` declarado e nunca importado | `requirements.txt` | ⏳ pendente |
| Conexões abertas fora do pool (`psycopg2.connect` direto em `manage.py`, `audit.py`, `auth.py`, `ingest.py`) — `DB_POOL_MIN/MAX` não cobrem esses caminhos | vários | ⏳ pendente |
| Isolamento por dono é *opt-in* por parâmetro: `user_id=None` desliga o filtro de escopo | `agent.py`, `regime.py` | ⏳ pendente |
| App sem rate limiting/lockout no login e sem exclusão de usuário | `main.py`/`auth.py` | ⏳ pendente |
| `audit_log` guarda pergunta e resposta para sempre, sem retenção/anonimização (LGPD, segredo de justiça) | `audit.py` | ⏳ pendente |
| Nenhum backup automatizado (a pasta `/srv/ia-juridico/backups` é criada e nunca usada) | `setup.sh` | ⏳ pendente |
| Imagem `ankane/pgvector` (não oficial, sem manutenção) e `runtime: nvidia` fixo (quebra host sem GPU, apesar de o setup prever modo CPU) | `docker-compose.yml` | ⏳ pendente |
| Caminhos absolutos `/srv/ia-juridico/*` no compose vs. `/opt/ia-juridico` no setup | `docker-compose.yml`/`setup.sh` | ⏳ pendente |
| Documentação divergente do código (README dizia `SIMILARITY_THRESHOLD` padrão 0.60 sendo 0.80; afirmava `cryptography` no requirements; `docs/AGENTS.md` descrevia o isolamento como "próxima fase" já implementado; `docs/TESTING.md` listava achados já resolvidos) | `README.md`, `docs/` | parcialmente corrigido |

---

## O que está sólido (e deve ser preservado)

* **Nenhum segredo real no histórico do git** — varredura de todo o histórico não achou
  token, chave privada ou senha verdadeira (só placeholders `***`/`****`).
* **Filtro de isolamento consistente** nos três caminhos de recuperação (semântico,
  metadados e palavra-chave), com a mesma forma de predicado.
* **Engenharia de RAG com medição**: HyDE + fusão RRF, re-ranking MMR, recuperação
  assimétrica (`search_document:`/`search_query:`) e relatórios em `app/eval/relatorios/`
  para comparar versões em vez de confiar em impressão.
* **Fact-check determinístico** (sem custo de latência extra) que pega citação fabricada
  e afirmação factual desancorada, com canonicalização de números por extenso.
* **Bom trabalho de prompt**: system (persona/regras) separado do human (contexto +
  pergunta), com regras explícitas de arbitragem entre regimes jurídicos.
* **158 casos de teste** verdes em 12 módulos, com mocks organizados e documentação de
  estratégia (`docs/TESTING.md`).

---

## Limitações desta revisão

* Não havia **Docker** nesta máquina: `docker compose`, o container Streamlit e o Ollama
  **não foram executados ponta a ponta**. As verificações de banco usaram um PostgreSQL
  16.2 local com pgvector, com o `database/init.sql` real.
* Os jobs novos do CI (lint/test/integração/schema) têm os **comandos verificados**
  localmente, mas o workflow em si nunca rodou no GitHub Actions.
* O comportamento visual do Streamlit (chaves duplicadas, mensagens) foi corrigido por
  leitura de código + testes da camada de dados; a interface não foi aberta.
* A interface não foi testada quanto a **acessibilidade**, i18n ou comportamento em
  navegadores corporativos.

## Como reproduzir as verificações principais

```bash
# 1. Suíte completa (um módulo por processo)
bash app/run_tests.sh

# 2. Integração contra um Postgres pgvector
docker run -d --name legal-test-db -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=senha -e POSTGRES_DB=legal_test -p 5440:5432 pgvector/pgvector:pg16
docker exec -i legal-test-db psql -U user -d legal_test -v ON_ERROR_STOP=1 < docs/legal_test_schema.sql
cd app && TEST_DATABASE_URL="postgresql://user:senha@localhost:5440/legal_test" \
  python -m unittest tests.test_integration_tenancy -v

# 3. O schema não pode semear admin (esperado: 0)
psql "$DATABASE_URL" -tAc "SELECT count(*) FROM users WHERE email='admin@legaliz.ai'"
```

> Para a chave do cookie, a verificação é a ausência de valor padrão:
> `grep -n 'COOKIE_KEY' app/main.py app/config.py` não deve mostrar literal nenhum.
