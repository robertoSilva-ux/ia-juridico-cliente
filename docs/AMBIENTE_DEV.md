# Ambiente de Desenvolvimento — Legaliz.ai

Como trabalhar neste projeto **nesta máquina** (Fedora 44, `homelab`), decidido em
2026-10-16. Para o ambiente do **cliente**, o caminho é o `docker-compose.yml` +
`setup.sh` (ver `README.md` e [`BACKLOG.md`](BACKLOG.md), itens P0-5 e P0-6).

---

## A decisão: híbrido (banco em container · Ollama e app nativos)

Não é "tudo local" nem "tudo container" porque as três camadas têm custos e ganhos
diferentes de paridade:

| Camada | Onde roda em dev | Por quê |
|:---|:---|:---|
| **Postgres + pgvector** | **Container** (`podman`, porta 5439) | É onde a paridade realmente morde: um Postgres nativo do Fedora seria PG 18 com pgvector compilado de outra forma, enquanto o cliente roda PG 16 com a extensão da imagem. Medido aqui: `pgvector/pgvector:pg16` traz **PostgreSQL 16.15 + vector 0.8.7** — a imagem `ankane/pgvector` que o compose do cliente usa está numa série antiga (ver P2-8). Custo em dev: zero (sem GPU, sem sudo). |
| **Ollama** | **Nativo** (`~/.local/bin/ollama`, 11434) | A app fala HTTP com ele: a interface é estável, então o ganho de paridade do container é pequeno. Já o custo em dev é grande: imagem CUDA pesada, rebuild a cada ajuste e, no compose, `OLLAMA_KEEP_ALIVE=5m` **descarrega o modelo** entre perguntas — péssimo para iterar prompt. |
| **Aplicação** | **Nativa** (venv 3.11 + Streamlit) | O `app/Dockerfile` copia o código no build (sem bind mount): cada edição viraria rebuild. Nativo dá traceback direto e reload instantâneo. |

> ⚠️ **O que o modo nativo esconde:** rodar com 31 GB de RAM mascara exatamente a
> restrição que vai machucar o cliente — o `mem_limit: 512m` do container `app`, onde
> o **P1-1** (fact-check carregando o corpus inteiro em memória) estoura. Por isso o
> **ensaio de paridade** (abaixo) não é opcional antes de qualquer release.

**Pré-requisito comum aos dois modos:** o driver NVIDIA roda **no host** — o container
apenas o consome. Nesta máquina ele já está ativo (615.78.08), então o Ollama usa GPU
nos dois cenários; sem driver, seria CPU.

---

## O que está instalado (estado em 2026-10-16)

| Peça | Situação |
|:---|:---|
| `podman` 5.8.7 rootless | já vinha no Fedora; `subuid`/`subgid` configurados |
| Banco de dev | container `legal-dev-db`, imagem `docker.io/pgvector/pgvector:pg16` (**Postgres 16.15 + vector 0.8.7**), porta 5439 |
| Ollama 0.40.5 | **serviço de sistema** (`/usr/local/bin/ollama`, unit `ollama.service`, `enabled`+`active`) — instalado pelo script oficial; modelos no home do usuário `ollama` (`/usr/share/ollama/.ollama`), **não** em `~/.ollama` |
| Modelos | `nomic-embed-text` (274 MB) + `phi4-mini:3.8b` (2,5 GB) — os dois de produção |
| Python | `python3.11` do Fedora (3.11.17, a mesma versão do `app/Dockerfile`) + venv `.venv` do projeto |
| GPU | RTX 3050 6 GB, driver **615.78.08 ativo** (`nvidia-smi` responde, `/dev/nvidia*` criados); Ollama já usando GPU |

> Não existe cópia manual do Ollama em `~/.local` — ela foi removida depois que o
> serviço de sistema ficou de pé (duas instalações do mesmo binário só geram dúvida
> sobre qual está rodando).

Detalhe que economiza dor de cabeça: em **podman rootless** é obrigatório o nome
completo da imagem (`docker.io/pgvector/pgvector:pg16`) — com o *short name* o podman
tenta perguntar o registro e falha sem TTY.

---

## Comandos do dia a dia

```bash
make db-dev          # sobe/religa o banco de dev (idempotente)
make db-dev-stop     # para o banco (os dados ficam no volume legal-dev-pgdata)

make dev             # app nativa: carrega o .env.dev e roda o Streamlit
make test-local      # suíte completa no host (usa o venv .venv)
make test            # suíte dentro do container — só no ambiente com Docker

bash scripts/db-dev.sh psql     # psql no banco de dev
bash scripts/db-dev.sh rm       # remove container + volume (começa do zero)

set -a; . ./.env.dev; set +a
.venv/bin/python scripts/smoke_dev.py    # ambiente de pé? (banco + embeddings + RAG + LLM)
```

O `smoke_dev.py` é o teste rápido do ambiente: ingere dois dispositivos, faz uma pergunta
e imprime resposta, fontes com distância e o veredito do fact-check. Ele falha se o Ollama
não responder, se o banco estiver inacessível, se nada for recuperado ou se a resposta vier
vazia — e **não** falha por qualidade do modelo (isso é papel do `app/eval/run_eval.py`).

O venv do projeto **já está criado** em `./.venv` (Python 3.11.17). Para recriar:

```bash
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r app/requirements.txt   # versões pinadas
```

Testes de integração contra o banco de dev (o mesmo fluxo do CI):

```bash
cd app
TEST_DATABASE_URL="postgresql://user:dev_local_senha@localhost:5439/legal_db" \
  python3 -m unittest tests.test_integration_tenancy -v
```

---

## Arquivos de ambiente: `.env.dev` × `.env`

| Arquivo | Para quê | Versionado? |
|:---|:---|:---|
| `.env.dev` | desenvolvimento **nativo**: `DATABASE_URL` e `OLLAMA_BASE_URL` em `localhost`, com `COOKIE_KEY`/`ADMIN_PASSWORD` próprios | não (`.gitignore`) |
| `.env` | **compose/cliente**: hosts `db` e `ollama`, que só resolvem dentro da rede do compose (o serviço `app` recebe via `env_file`) | não (`.gitignore`) |

Confundir os dois é o erro mais provável: com o `.env` do compose, a app nativa tenta
resolver o host `db` e falha. `scripts/dev.sh` deixa isso explícito no banner inicial.

---

## Ollama

Roda como **serviço de sistema** (instalado pelo script oficial), já habilitado para
subir no boot:

```bash
systemctl status ollama          # estado do serviço
sudo systemctl restart ollama    # reiniciar (ex.: depois de instalar driver)
ollama list                      # modelos instalados
ollama ps                        # o que está carregado (mostra CPU/GPU)
ollama pull <modelo>             # novo modelo
curl -s localhost:11434/api/version
```

Dois detalhes que confundem:

- os modelos ficam no home do **usuário do serviço** (`/usr/share/ollama/.ollama`), não
  em `~/.ollama` — por isso `du -sh ~/.ollama` não mostra nada;
- o `ollama` do PATH (`/usr/local/bin/ollama`) é só o **cliente**: quem serve a porta
  11434 é o processo do systemd, e os *runners* ficam em `/usr/local/lib/ollama`
  (é o caminho que aparece no `nvidia-smi`).

Medição nesta máquina (RTX 3050 6 GB, `phi4-mini:3.8b`): **carga fria ~80 s** (leva o
modelo para a VRAM) e **~43 tok/s** depois de carregado. A carga fria é o motivo de o
compose do cliente usar `OLLAMA_KEEP_ALIVE=5m` — e o motivo de, em desenvolvimento, valer
a pena manter o modelo aquecido enquanto se itera prompt.

**VRAM:** com o desktop (KDE + Firefox) a GPU já usa ~500 MB, sobrando ~5,5 GB. O
`phi4-mini:3.8b` ocupa 3,4 GB e cabe com folga; um modelo 8B quantizado (~5 GB) não
conviveria bem com o desktop. Na máquina do cliente (RTX 5060 Ti) não há essa restrição.

---

## Driver NVIDIA (GPU)

**Já instalado e ativo nesta máquina** — `nvidia-smi` responde com driver `615.78.08`,
`/dev/nvidia*` existem e o Ollama reporta uso de GPU (`ollama ps`). O que tornou o
caminho direto, verificado antes de instalar: RPM Fusion **free e nonfree já habilitados**,
**Secure Boot desabilitado** (não exigiu enrolar chave MOK), `akmods`/`kmodtool`
instalados e `kernel-devel` casando com o kernel em uso.

Para registro, foi exatamente isto:

```bash
sudo dnf install -y akmod-nvidia xorg-x11-drv-nvidia-cuda
modinfo -k "$(uname -r)" nvidia | head -3   # confirma que o kmod foi construído
```

Nesta máquina o módulo entrou em uso sem reboot (`lsmod | grep nvidia`,
`nvidia-smi`, `ollama ps` → GPU). O reboot continua recomendado quando possível, para o
sistema carregar o módulo desde o boot — o framework `akmods` já garante isso nas
próximas atualizações de kernel.

Conferência rápida:

```bash
nvidia-smi
ollama ps                    # "100% GPU" ou "x%/y% CPU/GPU" quando houver modelo carregado
```

---

## Ensaio de paridade antes de cada release (com Docker Compose)

O desenvolvimento nativo não exercita o que o cliente vai rodar. Antes de publicar:

0. **Se o banco do cliente já tem dados**, aplicar a migração de schema:
   `docker exec -i legal-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 < database/migrate_sources_owner.sql`
   (consolida fontes duplicadas, reaponta os chunks e cria o índice único novo — ver
   `docs/REVISAO_SEGURANCA.md`, addendum do P0-4).
1. `cp .env.cliente .env` e ajustar **senha do banco, `ADMIN_PASSWORD` e `COOKIE_KEY`**
   (o `setup.sh` recusa placeholders — isso é proposital).
2. `docker compose up -d --build` — com Docker (engine do cliente), não podman.
3. Conferir no stack containerizado:
   - o `mem_limit: 512m` do serviço `app` (**é aqui que o P1-1 aparece**);
   - `OLLAMA_KEEP_ALIVE=5m` (latência da primeira pergunta após pausa);
   - ingestão de um PDF real e uma pergunta de ponta a ponta com o modelo de produção;
   - o veredito do fact-check numa resposta correta (**P1-9**: hoje ele marca como
     "parcial" o que está certo — confirmar se a correção já entrou);
   - `docker compose config` para ver o efeito real do `env_file`.
4. Itens de infra que ainda estão abertos no backlog e valem checagem no ensaio:
   P0-5 (TLS/proxy + fechar a porta 5439), P1-7 (banco sem `ports:` no host),
   P2-8/P2-9 (imagem oficial do pgvector; `runtime: nvidia` condicional),
   P2-10 (caminhos `/srv` parametrizados), P2-11 (backup do volume).

---

## Depois de reiniciar a máquina

O reboot derruba o container do banco e o cache de VRAM do Ollama. O servidor do Ollama
volta sozinho (unidade `enabled`); o banco, não — religue com o script:

```bash
nvidia-smi                                 # GPU de pé
make db-dev                                # religa o banco de dev (idempotente)
systemctl is-active ollama && ollama list  # serviço de pé e modelos instalados

set -a; . ./.env.dev; set +a
.venv/bin/python scripts/smoke_dev.py      # ambiente OK? (a 1ª pergunta paga a carga fria ~80s)
make dev                                   # app em http://localhost:8501
```

**Login de desenvolvimento:** `dev@legaliz.local` (papel admin, criado pelo smoke test) —
a senha é a constante `SENHA_DEV` em `scripts/smoke_dev.py`; troque pelo painel se quiser
uma senha sua. Em máquina limpa, sem esse usuário, crie o admin com
`ADMIN_PASSWORD=... python app/init_admin.py` (a partir de `app/`).

**Primeira pergunta é lenta de propósito:** depois do reboot o modelo não está na VRAM, e
a primeira resposta paga a carga (~80 s nesta máquina). Do segundo prompt em diante a
latência fica em ~6-8 s. Se quiser evitar a espera durante o desenvolvimento, aqueça antes:
`ollama run phi4-mini:3.8b ""` ou simplesmente faça uma pergunta trivial ao subir.
