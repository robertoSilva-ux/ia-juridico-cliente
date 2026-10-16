# Evolução do projeto — Legaliz.ai

Diário de bordo do trabalho no repositório, em ordem cronológica, com o que foi
**verificado por execução** (não só escrito) e o que ficou pendente. Serve para retomar o
trabalho depois de uma pausa sem depender de memória de conversa.

Documentos irmãos: [`REVISAO_SEGURANCA.md`](REVISAO_SEGURANCA.md) (achados e evidências),
[`BACKLOG.md`](BACKLOG.md) (o que fazer, com critério de aceite), [`AMBIENTE_DEV.md`](AMBIENTE_DEV.md)
(como rodar na máquina de desenvolvimento) e [`adr/`](adr/) (decisões de arquitetura).

---

## Estado atual (2026-10-16)

| | |
|:---|:---|
| Branch / remoto | `main` local em `f432730`; **remoto ainda em `6fbbb9c`** (os dois commits do bloco 2 não foram publicados) |
| Suíte | **160 casos unitários em 12 módulos** + 14 de integração contra Postgres real — verdes |
| Lint | `ruff check .` limpo (o linter declarado no `pyproject.toml`) |
| Ambiente de dev | montado e funcionando: banco em podman (5439), Ollama em serviço + GPU, `.venv` 3.11, `make dev` |
| Bloqueadores de produção | **P0-5** (TLS + fechar a porta do banco) e **P0-6** (rotacionar credenciais que já circularam) — só o cliente pode executar |

### Como retomar

```bash
cd ~/Documentos/projetos/ia-juridico-cliente
git log --oneline -5                 # onde paramos
make db-dev                          # religa o banco de dev (depois de reboot)
set -a; . ./.env.dev; set +a
.venv/bin/python scripts/smoke_dev.py   # o ambiente está de pé?
cat docs/BACKLOG.md                  # a próxima tarefa (P1-1 ou P1-9)
```

Leitura rápida do [`BACKLOG.md`](BACKLOG.md): **P1-1** é o mais próximo de incidente real
(fact-check carregando a base inteira de todos os clientes num container de 512 MB) e
**P1-9** é o menor e mais visível (o aviso de "sem lastro" aparece em resposta correta).

---

## Bloco 1 — Revisão de segurança e correções P0 (2026-10-16)

**Pedido:** analisar o repositório do produto contratado por um cliente grande.

Análise feita a partir de clone limpo do commit `f613ad1`, com verificação por execução —
nada de conclusão baseada só em leitura:

| Verificação | Como | Resultado |
|:---|:---|:---|
| Senha do admin semeado pelo `init.sql` | `bcrypt.checkpw` | `admin123` confirmado |
| Forja do cookie de sessão | `pyjwt` + código-fonte da lib | assinatura **aceita** pela própria `streamlit-authenticator` (chave era o literal `legal_ai_key`, num repo público) |
| Vazamento entre donos (P0-3) | PostgreSQL real | um clique de escopo promovia o arquivo privado homônimo de outro usuário |
| Descarte silencioso na ingestão (P0-4) | PostgreSQL real | upload do 2º usuário com o mesmo nome era 100% filtrado |
| Segredos no histórico do git | varredura completa | **nenhum** (só placeholders) |

**Corrigido e commitado** (`ac69806`, `6fbbb9c`, publicados):

- P0-1 `COOKIE_KEY` vinda do ambiente, com validação de força (o app não sobe sem);
- P0-2 schema não semeia mais admin; `init_admin.py` recusa senha ausente/previsível;
  `setup.sh` valida as credenciais críticas antes de subir os containers;
- P0-3/P0-4 escopo, exclusão, dedup e `sources` por dono — nunca por nome de arquivo;
- infra: `env_file` no compose, dependências pinadas (+ lock), runner de testes único,
  `make test` consertado, CI com lint + testes + integração + verificação de schema;
- documentos: `REVISAO_SEGURANCA.md` e `BACKLOG.md`.

Ficou **pendente de propósito** (exige ação do cliente/servidor): P0-5 (TLS e fechar a rede)
e P0-6 (rotacionar as credenciais que já trafegaram em claro).

## Bloco 2 — Ambiente de desenvolvimento + correção de regressão (2026-10-16)

**Pedido:** decidir entre desenvolver local ou já em containers; preparar a máquina.

Decisão (ver [`adr/0004`](adr/0004-ambiente-de-desenvolvimento-hibrido.md)): **híbrido** —
banco em container, Ollama e aplicação nativos, com ensaio de paridade obrigatório antes de
release. Montado na máquina de desenvolvimento:

| Peça | Estado verificado |
|:---|:---|
| Banco | container podman **rootless** (sem sudo), Postgres **16.15 + pgvector 0.8.7**, porta 5439 |
| Ollama | 0.40.5 como **serviço de sistema** (`enabled`), `phi4-mini:3.8b` + `nomic-embed-text` |
| GPU | RTX 3050 6 GB, driver 615.78.08 ativo — `nvidia-smi` mostra os runners do Ollama na VRAM |
| Python | 3.11.17 (a mesma do container) + `.venv` com as dependências pinadas |
| Automação | `make db-dev`, `make dev`, `make test-local`, `scripts/smoke_dev.py` |

Medições: **~43 tok/s** de geração, **carga fria ~80 s** (leva o modelo para a VRAM) e
**6-8 s** por resposta já aquecida.

**Regressão encontrada na própria verificação e corrigida** (`42dc943`): o índice único
criado no bloco 1 usava `(file_name, owner_id)` cru, e como em índice único NULL é
distinto de NULL, o `ON CONFLICT` **nunca casava para documentos sem dono** — cada carga
em lote (`scripts/indexar_lote.py`, que roda com `--owner-id None` e é o caminho do corpus
global) inseria uma linha nova de `sources`. Corrigido com `COALESCE(owner_id, -1)` no
índice e no alvo do conflito, mais `database/migrate_sources_owner.sql` para banco que já
tenha dados (a migração reaponta os chunks **antes** de remover duplicatas — o FK é
`ON DELETE CASCADE`; testado: 2 fontes / 2 chunks → 1 fonte / 2 chunks preservados).

**Documentação** (`f432730`): `AMBIENTE_DEV.md`, scripts de dev, smoke test, `.gitignore`
(incluindo `.venv/`, que apareceria como não versionado).

### O que a execução revelou (e a leitura de código não mostraria)

**P1-9** — o fact-check marca como "parcial" as duas sentenças de uma resposta **correta**
(reproduzível com `scripts/smoke_dev.py`). Duas causas: formato do dispositivo
("artigo 25" vs "Art. 25.") e cobertura lexical de frase meta. Ainda **aberto**.

---

## Bloco 3 — Pós-reboot: a aplicação rodando e o login que não passava (2026-10-16)

**Pedido:** ver a aplicação rodando depois do reinício.

Ambiente confirmado: driver NVIDIA ativo, **Ollama subiu sozinho** como serviço com os dois
modelos, o container do banco estava `Exited` (esperado — o Ollama volta sozinho, o
container não) e voltou com `make db-dev`; `make dev` serviu a aplicação em
`http://localhost:8501` (`health: ok`, HTTP 200). O modelo entrou na VRAM (`ollama ps`:
3,6 GB, **100% GPU**) e a resposta quente ficou em **7,1 s** — a primeira do dia pagou a
carga (16 s no total).

### O login do smoke test foi recusado — e o smoke test não tinha como saber

A credencial do smoke test **autenticava**; quem não validava nada era o teste. Verificado
por execução, na ordem: `bcrypt.checkpw(senha do arquivo, hash do banco)` → True;
`Hasher.check_pw(...)` (a função interna que o login usa) → True;
`authentication_controller.login(email, senha)` (**o caminho exato do formulário**) → True;
o mesmo com senha errada → False (o teste tem poder de detectar); `validate_email` → True.

O smoke test fala com o banco direto e nunca exercitava o login: ficava verde com um login
que a interface poderia recusar — e isso já tinha acontecido antes, com a senha defasada.
**Corrigido:** ele agora monta o autenticador como o app o monta e chama
`authentication_controller.login(...)`. Se a senha gravada não servir, **redefine** com
`auth.update_password` (o arquivo passa a ser a fonte da verdade) e falha se ainda assim não
autenticar. A última linha imprime o par usuário/senha para entrar na aplicação.

**Usuários que confundem:** `alice@tenant-a…`, `bruno@tenant-b…`, `admin@legaliz.ai` e
`test@legaliz.ai` existem no banco de dev porque são **fixtures dos testes de integração**,
gravadas com `password_hash = 'x'` (hash inválido de propósito). Não são logins — e
`admin@legaliz.ai` é justamente o e-mail que o README cita para admin. No banco de dev a
única credencial utilizável é `dev@legaliz.local`.

### Três defeitos no próprio ferramental (todos encontrados rodando, todos corrigidos)

1. **`app/run_tests.sh` usava o `python3` do PATH**, não o interpretador do projeto: nesta
   máquina o primeiro do PATH é um 3.14 auxiliar sem `langchain_ollama`, então
   `test_regime_db` estourava com `ModuleNotFoundError` e o veredito da suíte variava com o
   ambiente de quem rodava. Agora prefere `VIRTUAL_ENV` → `.venv/` → `python3` (o container
   cai no último, como antes) e imprime o interpretador usado. `scripts/dev.sh` já estava
   correto.
2. **`test_config_cookie::test_chave_ausente_e_recusada` media o ambiente**: `None` significa
   "use `config.COOKIE_KEY`", então o resultado dependia de a variável existir no ambiente
   (existe, depois de carregar o `.env.dev`). Agora o teste fixa o valor do módulo com
   `patch` e vale nos dois casos.
3. **Os testes de integração apagam `documents`/`sources` do banco onde rodam** e deixavam os
   usuários-fixture para trás. Apontar `TEST_DATABASE_URL` para o banco de dev (ou, pior,
   para o de um cliente) apagaria dados reais — é a origem dos usuários-fantasma acima.
   Agora os dois módulos **se recusam a rodar** fora de um banco com `test` no nome, com
   aviso explicando o motivo (a convenção é `legal_test`, porta 5440).

Também corrigido neste bloco: o smoke test tratava **erro de chave duplicada como fatal**,
então a partir da segunda execução ele falhava sempre (o critério agora é "o usuário existe
ao final?", que é idempotente), e o nome do cookie de sessão saiu do literal em `main.py`
para `config.COOKIE_NAME` — assim o smoke test monta o autenticador exatamente como o app.

### Achados novos

- **P2-25** — o Streamlit avisa que `st.components.v1.html` "will be removed after
  2026-06-01", data **já passada** (funciona porque a versão está pinada): o próximo bump
  pode derrubar a página.
- **P2-26** — o `phi4-mini:3.8b` erra o próprio rótulo (`"OBRJETO"` em vez de `OBJETO`), e
  os "parcial" do fact-check são exatamente os rótulos que o prompt exige (`OBJETO`,
  `RESPOSTA`, `ARBITRAGEM DE REGIME JURÍDICO`). O **P1-9 não é alucinação**: é o formato
  imposto virando sentença "verificável" sem lastro.

### Estado ao fim do bloco

Suíte **160 casos em 12 módulos, verdes** sob o interpretador do projeto; `ruff check .`
limpo; aplicação servindo em `http://localhost:8501`; login de dev verificado pelo caminho
do formulário; guarda de banco de teste ativa nos módulos de integração.

## Pendências (detalhe e critério de aceite no BACKLOG)

| Item | Onde | Por que ainda não foi feito |
|:---|:---|:---|
| **P0-5** TLS + fechar a porta 5439 | infra do cliente | depende do servidor/proxy do cliente |
| **P0-6** rotacionar credenciais | operação | as chaves já circularam em HTTP e com o banco exposto |
| **P1-1** fact-check escopado por dono e com memória limitada | `app/factcheck.py` | mais próximo de incidente (OOM no container de 512 MB e validação cruzada entre clientes) |
| **P1-2** estado global de LLM entre sessões | `app/agent.py` | qualquer usuário troca o modelo de todos |
| **P1-6** PDF escaneado falha em silêncio | `app/ingest.py` | precisa de mensagem de erro (OCR é decisão de produto) |
| **P1-8** prompt injection indireta | `app/prompts/` | mitigação a definir com o cliente |
| **P1-9** falsos positivos do fact-check | `app/factcheck.py` | pequeno, com reprodução pronta |
| P2 (14 itens) | vários | melhorias e riscos aceitáveis no curto prazo |

### Decisões operacionais em aberto

1. **Publicar ou não** os commits `42dc943` e `f432730` (`git push origin main`) — estão
   locais.
2. **Rotação do login de desenvolvimento**: o usuário `dev@legaliz.local` é criado pelo
   smoke test com senha conhecida; trocar pelo painel quando o ambiente for compartilhado.
