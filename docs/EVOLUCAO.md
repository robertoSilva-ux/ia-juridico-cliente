# Evolução do projeto — Legaliz.ai

Diário de bordo do trabalho no repositório, em ordem cronológica, com o que foi
**verificado por execução** (não só escrito) e o que ficou pendente. Serve para retomar o
trabalho depois de uma pausa sem depender de memória de conversa.

Documentos irmãos: [`REVISAO_SEGURANCA.md`](REVISAO_SEGURANCA.md) (achados e evidências),
[`BACKLOG.md`](BACKLOG.md) (o que fazer, com critério de aceite), [`AMBIENTE_DEV.md`](AMBIENTE_DEV.md)
(como rodar na máquina de desenvolvimento), [`adr/`](adr/) (decisões de arquitetura) e
[`CONFORMIDADE_REQUISITOS.md`](CONFORMIDADE_REQUISITOS.md) (o que o produto entrega de cada
requisito de [`requisitos_gerais.txt`](requisitos_gerais.txt), e o que falta).

---

## Estado atual (2026-10-20)

| | |
|:---|:---|
| Branch / remoto | `main` em **`bda0a49`** local (remoto ainda em `bad3c0d` — push é decisão do Roberto). Os blocos 9 (corpus oficial), 10 (P2-32) e 11 (peso por regime) estão commitados em `a4d33a2` e `bda0a49`; árvore limpa, exceto `docs/requisitos_gerais.txt` (arquivo do usuário, ainda vazio) |
| Suíte | **301 casos em 14 módulos** verdes, também sob ambiente limpo (`env -i HOME=$HOME PATH=$PATH bash app/run_tests.sh`, medido 2026-10-20) + 14 de integração contra Postgres real (`scripts/ci_integracao_local.sh` do skill) |
| Lint | `ruff check .` limpo — **precisa ser o do venv**: fora dele o comando não existe (`.venv/bin/python -m ruff check .`) |
| Ambiente de dev | montado e funcionando: banco em podman (5439), Ollama em serviço + GPU, `.venv` 3.11, `make dev` |
| Modelo padrão | `phi4-mini:3.8b` @ `LLM_NUM_CTX=8192` — decisão registrada no ADR-0008 |
| Garantia de lastro | três barreiras (suficiência → lastro no fragmento citado → portão de exibição) — ADR-0009 |
| Ingestão | preâmbulo (texto antes do 1º dispositivo) **entra no índice** rotulado como `preambulo`, identidade da norma lida das páginas cruas — ADR-0010; aceita **PDF e `.txt`** (página sintética a cada ~4.000 chars) — ADR-0011 |
| Base de dev | **1.984 fragmentos / 1.193.190 chars** em 6 arquivos. Corpus **oficial do Planalto** (1.981 fragmentos, escopo `global`, `numero_doc`/`ano_doc` em **100 %**): `d3048.txt` (1.716), `l8080.txt` (141), `emc103.txt` (116), `lcp142.txt` (8). Restos de medição: `Lei 8.213-91.pdf` (2), `peticao.pdf` (1, isolamento do P1-1). A **apostila `LEI-8080-ESQUEMATIZADA1.pdf` foi removida** da base em 2026-10-20 (backup dos 157 fragmentos em `.backups/apostila-8080-2026-10-20.json`; o PDF segue em `~/Downloads`) |
| Bloqueadores de produção | **P0-5** (TLS + fechar a porta do banco) e **P0-6** (rotacionar credenciais que já circularam) — só o cliente pode executar |

### Como retomar

```bash
cd ~/Documentos/projetos/ia-juridico-cliente
git log --oneline -5                 # onde paramos
git status --short                   # blocos 9 e 10 ainda não commitados (decisão do Roberto)
make db-dev                          # religa o banco de dev (depois de reboot)
set -a; . ./.env.dev; set +a
.venv/bin/python scripts/smoke_dev.py   # o ambiente está de pé?
cat docs/PLANO_REFINAMENTO_RAG.md     # Fases 1 e 2 fechadas; Fase 3 (recuperação) é a próxima
```

Leitura rápida: **Fases 1 e 2 do plano estão executadas**, incluindo o R-24/R-25 (bloco 8); o
**corpus oficial do Planalto** entrou (P2-30, bloco 9) e a **dominância de documento** que ele
expôs está resolvida (P2-32, bloco 10). O que sobra do pedido "resposta 100 % fundamentada ou
recusa honesta" é o resto da **Fase 3** — **R-15** (a via de metadados devolve direto e entrega 1
trecho), **R-16** (portão relativo) e **R-18** (contexto por tokens): os três se medem com o mesmo
instrumento criado no bloco 10 (`app/eval/medir_origem_contexto.py` + o mini-quiz). **P1-2**
(estado global do LLM) vem na Fase 4.

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

## Bloco 4 — Retorno da ingestão de arquivos (2026-10-16)

**Pedido:** "precisa revisar o frontend da ingestão de arquivos. Em algumas versões atrás,
mostrava o percentual de ingestão de múltiplos arquivos e sinalizava a conclusão; fiz a
ingestão de 1 arquivo, e só vi que havia concluído porque apareceu na tabela abaixo."

### Diagnóstico (três coisas distintas, uma só era regressão)

1. **A confirmação era destruída no instante em que era criada.** O código terminava com
   `st.success(...)` **seguido de** `st.rerun()`; o rerun descarta a renderização da execução
   atual. O padrão estava em **6 pontos** do `main.py` (ingestão privada e global, exclusão de
   fragmentos ×2, cadastro de usuário, troca de senha) e havia ainda **2 ações silenciosas**
   (trocar o escopo de um documento só dava `st.rerun()`, sem mensagem nenhuma). `st.toast`
   (o componente que sobrevive ao rerun) não era usado em lugar nenhum.
2. **A barra não tinha o que mostrar com um arquivo.** O progresso vem de
   `store_in_postgres`, que emite **um valor por lote** (`EMBED_BATCH_SIZE=128`): qualquer PDF
   com menos de 128 fragmentos emite um único 100%, na mesma execução que o rerun descarta.
3. **A ingestão múltipla não existe neste repositório — nem no histórico dele.**
   `accept_multiple_files` nunca apareceu em commit algum: o histórico começa em `def535b`
   ("deploy cliente — repositório limpo sem estrutura aninhada"), que é o commit-raiz. A
   interface lembrada pelo usuário está numa cópia anterior a essa limpeza. Não há branches
   nem tags antigas para recuperar dela.

### O que foi feito (decisão do usuário: correção mínima, 1 arquivo, mais os 6 pontos)

- **`app/ui_feedback.py` (novo)**: `flash()` + `render_flash()` — o retorno da ação passa pelo
  `session_state` e aparece **uma vez** na execução seguinte, em qualquer página (ver
  [`adr/0006`](adr/0006-retorno-de-acao-sobrevive-ao-rerun.md)). Aplicado nos 8 pontos.
- **Ingestão com estágio, não só porcentagem**: o componente mostra
  `extraindo e fragmentando o PDF` (0–50%) e depois `gerando embeddings e gravando` (50–100%)
  dentro de um `st.status`.
- **O retorno passou a vir do backend**: a interface usa o `ingest_document()` que já existia
  (usado só pelo script de carga em lote) em vez de repetir `process_pdf` + `store_in_postgres`
  inline — e passou a **contar** o que foi gravado.
- **P1-6 fechado por consequência**: 0 fragmentos (PDF escaneado ou tudo já na base) agora é
  **aviso explícito**, nunca "indexado com sucesso".
- **Defeito no backend corrigido**: `ingest_document` prometia "número de chunks indexados" e
  devolvia o **número de lotes** (somava yields) — 1 para um PDF de 128 fragmentos, 3 para um
  de 300; o script de carga em lote exibia isso como total. Agora `store_in_postgres` aceita
  `stats=` (canal aditivo: os yields continuam sendo floats, sem quebrar quem já consumia) e a
  função devolve `indexados` de verdade.
- Unificado o que estava divergente entre os dois blocos de ingestão: o da aba do admin usava
  `os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")` e o modelo de embedding hardcoded;
  agora ambos vêm de `config` (`OLLAMA_BASE_URL`, `EMBEDDING_MODEL`).

### Verificação

- `ruff check .` limpo; suíte **172 casos em 13 módulos** (12 novos: contagem de fragmentos,
  `stats`, e o retorno de ação incluindo o caso negativo) — todos passando.
- **Visual, em página de prévia isolada** (sem banco, Ollama ou login): capturas do *durante*
  (painel "Indexando …, gerando embeddings e gravando — 60%") e do *depois* (faixa verde
  "'Lei 8.213-91.pdf' indexado: 12 fragmento(s) no escopo private.").
- Dois testes meus falharam na primeira execução e os dois eram erros **meus**, não do código:
  uma expectativa errada sobre o dedup e um duplo de Streamlit (`MagicMock`) que tornava
  impossível falhar o caso de tipo desconhecido — trocado por um duplo fiel, em que atributo
  inexistente levanta (como no Streamlit real).

### Deixado para depois (com registro no backlog)

- **P2-28** — a fila de múltiplos arquivos (o que o usuário lembra), adiada de propósito nesta
  rodada; o componente já aceita ser chamado em laço.
- **P2-27** — `database.py` monta o pool **no import**: descoberto ao montar a prévia, porque
  importar a app com o `DATABASE_URL` padrão (host `db`, do compose) quebra antes de qualquer
  UI — e no Streamlit o `config` cacheado entre reruns mantém o DSN ruim do primeiro run.

## Bloco 5 — Identidade da norma no fact-check, rótulo da fonte e o caso "Lei 8.080" (2026-10-16)

**Pedido:** *"as respostas do modelo estão bem ruins e incorretas, espero melhorar isso enquanto
avançamos"* — com quatro respostas sobre a Lei Orgânica da Saúde em que o modelo citava
**"Lei nº 8.830, de 1993"** e **"Lei nº 13.137, de 5 de agosto de 2016"** (a Lei Orgânica da
Saúde é a **8.080/1990**).

### Diagnóstico: a busca estava certa; o selo de verificação é que era falso

| Verificação | Medição |
|:---|:---|
| Recuperação | **OK** — 15 fragmentos, distâncias 0,24–0,35, 6–8,7 mil caracteres da lei certa no contexto |
| Origem dos números inventados | **composição**: `8080` vinha do **nome do arquivo** (`LEI-8080-ESQUEMATIZADA1.pdf`, no cabeçalho de cada `[DOC]`) e `2011` de um trecho de **outra** lei — *"(Incluído pela Lei nº 12.401, de 2011)"* |
| Fact-check | **`all_grounded: True` na resposta errada**: verificava dispositivos e quantidades ("art. 25", "180 dias"), **nunca a identidade da norma** (lei + ano) |
| Confirmação independente | nos relatórios dos próprios autores (`app/eval/relatorios/bench_*20x.json`, 5 modelos, ~200 execuções) `no_support` foi **0,00 em todas** — a checagem nunca reprovava nada |
| Identificação da fonte | `sources.numero_doc`/`ano_doc` **NULL** e `title` degenerado (`"Lei"`): o parser exigia espaço dos dois lados do número, então `LEI 8080.pdf` e `LEI-8080-ESQUEMATIZADA1.pdf` davam `numero=None` |

### O que foi feito

- **A — checagem de identidade de norma** (`app/factcheck.py`, ver [`adr/0007`](adr/0007-fact-check-exige-par-numero-ano.md)):
  toda citação de lei/decreto/EC é extraída (número e ano normalizados) e conferida contra o
  contexto com **regra de par** — número e ano têm de aparecer juntos no conteúdo de um mesmo
  fragmento. Severidade em três níveis: `norma_sem_lastro` (número inexistente),
  `ano_incompativel` (número existe com outro ano), `ano_nao_consta` (ano não verificável →
  `partial`). A identidade do próprio documento (metadado ou nome do arquivo) conta como lastro
  para **aquela** norma, mas nunca forma par com o ano de outra lei.
- **B — identificação da fonte no contexto** (`app/legal_parser.py`, `app/ranking.py`): o parser
  passou a ler `LEI 8080.pdf`, `LEI-8080-ESQUEMATIZADA1.pdf` e `lei_8213_1991.pdf` (sem
  confundir `CF-88` com lei 88) e o rótulo inclui o ano, com fallback para o nome do arquivo —
  o que corrige **as bases já ingeridas**, sem migração:
  `[DOC 1] — Lei` → `[DOC 1] — Lei 8080`.

### Verificação

- **182 casos em 13 módulos** verdes (11 novos: extração de citações, os três níveis de
  severidade, o caso real reproduzido e a guarda contra falso positivo), `ruff` limpo.
- **Na base real**, a pergunta que produzia o erro passou de `all_grounded: True` para
  `False` com motivo explícito; e o `phi4-mini` foi apanhado inventando em outra questão:
  *"Art. 19-B da Lei nº **8.826, de 1991** ... Lei de **Reforma da Previdência Social, ou
  REPS**"* — **duas normas sem lastro** que antes passavam com selo verde.
- Um teste **meu** falhou na primeira execução e o defeito era dele: `test_ui_feedback` exigia
  banco alcançável só para ser importado (o pool no import, P2-27) e quebrava de forma
  intermitente em ambiente limpo. Corrigido com duplos dos módulos da app.

### Medição de modelos: o que valeu, o que não valeu, e a GPU que caiu

Mini-quiz de 7 perguntas com resposta verificável **no corpus existente** (o oficial — Decreto
3.048, LC 142, EC 103 — vive no servidor do cliente e não está nesta máquina), incluindo uma
pergunta-armadilha cujo tema não está na base. Cada série foi classificada pela janela em que
rodou, o que descartou boa parte dela:

| modelo | janela | recall | normas inventadas | `grounded` | mediana | confiabilidade |
|:---|:---|--:|--:|--:|--:|:---|
| `phi4-mini:3.8b` | 02:38–02:53 | 0,50 | **4** | 7/14 | **7 s** | ✅ GPU sã |
| `qwen2.5:7b` | 02:53–03:07 | 0,50 | **0** | 10/12 | 38 s | ⚠️ 1ª iteração antes do erro de CUDA |
| `llama3.1:8b` | 03:07–03:32 | 0,53 | 0 | 8/14 | 86 s | ⚠️ GPU já instável |
| `gemma3:4b-it-qat` | 03:32–03:53 | 0,44 | 3 | 0/14 | 94 s | ⚠️ idem |
| `qwen3:4b` | 03:53–… | 0,67 | 1 | 0/6 | **674 s** | ❌ pós-AER (CPU) |
| `qwen2.5:7b @4096` | 04:03–04:34 | 0,38 | 1 | 10/14 | 141 s | ❌ pós-AER + 2 bancadas |
| `gemma2:9b @4096` | 04:34–05:17 | 0,44 | 0 | 5/14 | 165 s | ❌ idem |

**Dois erros meus nesta rodada, registrados porque custaram tempo e números:** (1) deixei duas
bancadas rodarem ao mesmo tempo, e o Ollama então recarrega o modelo a cada requisição — as
latências de 100–480 s são contenção, não memória; (2) tratei como "VRAM" o que era, em parte,
**falha de hardware**: às 04:07 a placa **caiu do barramento PCIe**
(`nvidia 0000:03:00.0: AER: can't recover`, repetido por ~1 h), e o `qwen3:4b` — modelo de
2,5 GB que **cabe** nos 5,06 GB livres — passou a responder em 498 s, 674 s, 1154 s e **1845 s**,
tudo em CPU. A lição de método: bancada de modelo roda **uma por vez**, com `ollama stop` entre
elas, e o estado da GPU é pré-requisito da medição, não detalhe.

**O que sobrevive de sólido** (métricas de conteúdo não dependem de CPU/GPU): o `phi4-mini`
inventa número de lei (4 casos) e os modelos maiores não (0 e 0; 3 no gemma3); **nenhum**
modelo acerta a pergunta-armadilha (recusa correta entre 0,00 e 0,14); e o orçamento de VRAM é
decisivo — com o desktop, o Ollama enxerga **5.060 MiB livres de 5.855**: 2,5 GB roda liso
(7 s), 4,0 GB é limítrofe, ≥4,7 GB vai para a CPU (86–200 s) e, sem GPU, o produto **para**
(P1-10).

**Fechado no ciclo limpo** (após reboot, GPU sã, fila **em série** com `ollama stop` entre modelos,
14 respostas por modelo, 5,6 GB livres de 6,1 GB):

| modelo | recall | normas inventadas | `grounded` | recusa (armadilha) | mediana | onde o Ollama pôs |
|:---|--:|--:|--:|--:|--:|:---|
| `phi4-mini:3.8b` | **0,56** | 2 | 7/14 | 0,21 | **7 s** | **100 % GPU** |
| `gemma3:4b-it-qat` | 0,50 | 2 | 2/14 | 0,07 | 14 s | 95 % GPU |
| `qwen3:4b` | 0,50 | 1 | 2/14 | **0,29** | 125 s | 100 % GPU |
| `qwen2.5:7b @4096` | 0,38 | **0** | 9/14 | 0,07 | 17 s | 84 % GPU (16 % CPU) |

Isto **fecha** a medição e confirma por conta própria a decisão do
[`adr/0008`](adr/0008-modelo-por-orcamento-de-vram.md) (`phi4-mini:3.8b` @ `LLM_NUM_CTX=8192`):
melhor recall, 7 s por resposta e 100 % na GPU (comportamento previsível). O defeito do modelo
pequeno — inventar número de lei (2 casos) — é exatamente o que o fact-check do [`adr/0007`](adr/0007-fact-check-exige-par-numero-ano.md)
passou a reprovar. O `qwen2.5:7b`, único sem invenção (0), **não cabe** (5,2 GB carregados, 16 %
das camadas na CPU) e perde no recall (0,38) — o que ele oferecia, o fact-check agora garante. O
`qwen3:4b` está fora para chat: 125 s por resposta (modo de raciocínio), mesmo em 100 % GPU.

**Achado operacional que vira requisito de dimensionamento:** com um modelo de 3,6–3,9 GB na VRAM,
o `nomic-embed-text` foi empurrado para **74 % CPU / 26 % GPU** — e os embeddings são usados em
*toda* pergunta e em *todo* fragmento na ingestão. Regra: modelo de chat **≤ ~3,9 GB** no contexto
8192, para não expulsar os embeddings da placa.

**Ressalva de método (defeito no meu ferramental, corrigido):** o vigia que reportou este ciclo
agregava *todos* os `resultado_*.json`, misturando modelos que não rodaram nesta janela — inclusive
dos ciclos com a GPU caída (`llama3.1:8b`, `gemma2:9b`) e uma duplicata antiga do `qwen2.5:7b`.
Os scripts agora leem um marco de ciclo (`date +%s > ciclo.inicio`) e ignoram arquivos anteriores a
ele; a mensagem publicada no WhatsApp foi corrigida à mão. **Ninguém recusa bem a pergunta-armadilha**
(0,07–0,29) — comportamento, não tamanho de modelo: segue em P1-9/P2-26.

## Bloco 6 — Fundamentação e recusa honesta: o portão de resposta (2026-10-16)

### Pedido e escopo

> "Confirmado o modelo, agora vamos refinar o código, o prompt, a ingestão de informação, o chunk,
> a gravação e a recuperação do banco de dados. Precisamos de respostas 100 % fundamentadas no rag
> ou a honestidade de dizer que não encontrou."

Modelo confirmado por ele: **`phi4-mini:3.8b`** (ADR-0008). Escopo escolhido em formulário: **Fase 1
do `docs/PLANO_REFINAMENTO_RAG.md` (R-1 a R-8)** — a garantia visível, sem tocar na base — **e**
trazer texto oficial do Planalto para calibrar a recusa. O texto oficial **não** foi trazido neste
bloco: ele muda a base e obriga a remedir tudo, então anda junto da Fase 2 (ver "Em aberto").

### Diagnóstico (medido antes de escrever código)

1. **A não-resposta passava com selo verde.** "Prazo de prescrição da usucapião extraordinária" (fora
   da base) → *"A vigência não está indicada nos documentos recuperados."*, com 15 fontes a 67–69 %
   de similaridade e `all_grounded: True`. O veredito do fact-check era **calculado e descartado** em
   `main.py`.
2. **Limiar de distância não separa "a base responde" de "não responde":** top-1 de 0,15–0,27 nas
   perguntas com resposta na base contra 0,20–0,35 fora. O `SIMILARITY_THRESHOLD=0.80` não é portão.
3. **Distância fabricada:** a busca por metadados/palavra-chave devolvia `distance = 0.0` e a
   interface escrevia "Similaridade: 100,00 %"; `FACT_CHECK_LLM_ENABLED` era config morta.
4. **Estado da base de dev:** 120 de 122 fragmentos sem `numero_doc`, um fragmento de 17 caracteres
   indexado e o rodapé do professor dentro do primeiro `[DOC]` de toda consulta.

### O que foi feito

- **`app/agent.py`** — portão de suficiência (`_contexto_suficiente`, prompt próprio, 0,5–2,0 s);
  recusa canônica escrita pelo sistema (`_texto_recusa`, com contagem de trechos, motivo e o que
  fazer); **uma** segunda leitura (reescrita ancorada para `sem_lastro`, nova procura para recusa);
  `_montar_sources` com distância real/origem/citada; auditoria com prefixo `[RECUSA: motivo]`.
- **`app/factcheck.py`** — veredito da resposta (`fundamentada` · `parcial` · `recusou` ·
  `sem_lastro`), lastro conferido **no fragmento citado**, recusa reconhecida pela primeira frase,
  citação aceita nas duas grafias (`[3]` e `[DOC 3]`).
- **`app/prompts/system-role.md`** — contrato de saída verificável (`[DOC n]` por frase com dado
  concreto), recusa como **último recurso** e sem seção obrigatória de regime (era ela que gerava
  frase não verificável e falso positivo no fact-check).
- **`app/ui_feedback.py` + `app/main.py`** — `montar_resposta`/`render_resposta`: a resposta chega à
  tela com veredito, ressalva, recusa destacada e fontes que dizem se foram citadas.
- **`app/regime.py`** — fim da distância falsa (`NULL` + `origem` em vez de `0.0`).
- **`app/config.py`, `.env.example`, `README.md`** — `FACT_CHECK_LLM_ENABLED` agora descreve o que
  faz (portão de suficiência) e passa a `true`.
- **`app/eval/`** — mini-quiz do corpus de dev (`quiz_dev_lei8080.json`, com a pergunta-armadilha),
  `medir_portao.py` e `medir_a4_repetido.py` (R-22 parcial).

### Verificação (por execução, GPU sã)

- Suíte **227 casos em 13 módulos** verdes (eram 182; **45 novos**), rodada hermética
  (`env -i HOME=$HOME PATH=$PATH bash app/run_tests.sh`), `ruff check .` limpo.
- Fim a fim no banco real: **A1 = 0** resposta exibida com norma/dispositivo sem lastro ·
  **A2 = 7/7** recusas honestas (armadilha + 6 perguntas fora da base) · **A4 = 15/18 (83 %)**
  perguntas legítimas respondidas em 3 iterações · latência mediana 7,9 s, **p95 10,6 s**.
- Leitura da UI sem digitar senha: os 4 estados de `montar_resposta` têm teste com duplo fiel.

### Cinco defeitos que só a medição mostrou

1. O verificador **não aceitava o formato de citação que o prompt manda usar** (`[DOC n]` vs `[n]`):
   4 de 5 perguntas legítimas eram recusadas — a d1 respondia 5/5 em chamada isolada e era recusada
   no fluxo. Só apareceu instrumentando o `CHAIN`.
2. Bloquear resposta sem citação **descartava resposta correta** (d2: "os municípios podem
   constituir consórcios…"). `sem_fonte` virou aviso.
3. O retry que terminava em recusa disparava uma **terceira** chamada e perdia a resposta boa da
   primeira.
4. Recusa em prosa ("A base não contém informações… pelo art. 55") estava sendo classificada
   **fundamentada**, porque a menção ao art. 55 contava como "unidade verificável".
5. O modelo escreve a recusa deformada ("NÃO ENCONTRAR NA BASE") e ela passava como resposta.

### Em aberto (honesto)

- **A4 = 83 %, não 100 %:** o 3,8 B recusa de forma instável perguntas que o material responde
  (d4 sempre, d5 e d1 às vezes). O portão diz "SIM" e a segunda leitura não resolve — é limite do
  modelo, não do portão. Caminho: Fase 2 (corpus oficial + identidade da norma por documento),
  Fase 3 (portão relativo, fim da via de metadados que substitui a semântica) e resposta extrativa.
- **Texto oficial do Planalto** (decisão dele, não executada): planejada para a Fase 2, porque muda a
  base e exige reingestão + nova medição.
- **Commit/push dos blocos 5 e 6**: decisão dele, não feita.

---

## Bloco 7 — P1-1, Fase 2 e três defeitos que só o dado real mostrou (2026-10-16)

Escopo: **P1-1** (fact-check escopado por dono) e a **Fase 2** do plano de refinamento
(R-9 a R-13: identidade da norma por documento, limpeza de ruído de página, dedup por hash,
rastreabilidade). A GPU não mudou de estado: **nenhuma nova medição de A4/A2** neste bloco —
o que se mediu foi a **base** (ingestão, chunk, gravação), com o PDF de origem de volta.

### P1-1 — fact-check escopado por dono e com memória limitada

`_load_dispositivos_base` carregava a base inteira (medido antes: 53 dispositivos / 61 KB /
106 ms) e **validava o texto citado contra o documento de outro cliente**. Agora:

- a consulta é escopada (`scope='global' OR owner_id=%s`, legado `owner_id IS NULL`) e o
  cache é **por dono** (`_DISPOSITIVOS_BASE_CACHE`), com teto de linhas e de caracteres
  (`FACT_CHECK_CACHE_MAX_ROWS=20000`, `FACT_CHECK_CACHE_MAX_CHARS=8000000`);
- `user_id` atravessa `_check_semantic_grounding` → `_fact_check_answer` → `agent`;
- medido: um fragmento do dono B deixou de ser validado por pergunta do dono A.

### Fase 2 — executada (R-9 a R-13)

| Item | O que mudou | Como foi verificado |
|:---|:---|:---|
| **R-9** identidade da norma | `identidade_do_documento` lê a norma no **conteúdo** do documento (cabeçalho/título) e assume o nome do arquivo como segunda fonte; a identidade vai para `sources` e para todos os fragmentos | 20 casos de cabeçalho real + 4 regressões do que NÃO pode virar identidade |
| **R-10** ruído de página | `limpar_ruido_de_pagina` compara linhas com espaços colapsados e números normalizados (≥50 % das páginas, mín. 3), remove linha de número de página e **preserva** a linha que carrega identidade de norma/dispositivo | no PDF real: rodapé do cursinho em **40 → 0** fragmentos |
| **R-11** fragmento degenerado | descarta o fragmento que ficou **vazio** após a limpeza — e **não** por tamanho | medido no dado real: "Art. 40. (Vetado)" tem 17 chars e é lei vigente |
| **R-12** dedup no banco | `content_hash` (md5) + índice único `documents_file_owner_hash_uidx`; ingestão com `ON CONFLICT (file_name, (COALESCE(owner_id, -1)), content_hash) DO NOTHING`, contando o que o banco inseriu (`rowcount`) | em **Postgres real**: duplicata direta rejeitada pelo índice, `ON CONFLICT` da ingestão sem erro, mesmo conteúdo de outro dono entra |
| **R-13** rastreabilidade | colunas `pagina` (1-based) e `ordem` | no banco real e em teste |

Suíte: **266 casos em 14 módulos** verdes; `ruff check .` limpo.

### Os três defeitos que só apareceram com o PDF de origem em mãos

O PDF da apostila **não tinha desaparecido** — está em `~/Downloads/LEI-8080-ESQUEMATIZADA1.pdf`.
Com ele, três coisas que o teste unitário não pega:

1. **A identidade saía de uma norma CITADA.** Com o cabeçalho de 4.000 caracteres, a primeira
   "norma" do texto da apostila é `Decreto nº 1.651, de 28 de setembro de 1995` (pos. 2.113) —
   linha da **lista de leis que alteraram** a 8.080. Todos os 109 fragmentos receberiam a
   identidade errada. Correções: cabeçalho lido em 2.000 caracteres, padrão para o título em
   prosa (o material didático escreve "a Lei 8.080, de 19 de setembro de 1990", sem "Nº") e
   **escolha por posição, não por padrão** — com pistas de citação ampliadas
   ("na forma da", "de acordo com", "segundo", "previstos no").
2. **O rodapé tinha duas grafias.** O rodapé do cursinho aparece com tabs
   (`Prof.\tAdriano\tde\tOliveira…`) e com espaços; a chave de comparação não unia as duas, e
   **3 fragmentos** escapavam da limpeza. Com espaços colapsados na chave: 40 → **0**.
3. **36 % do documento nunca entra no índice.** Ver item **R-24** do plano: o texto anterior ao
   primeiro `Art. N` é descartado em silêncio — no PDF real, as páginas 0–24 (**34.726 de
   96.246 chars**), que incluem a capa, o título da lei e a lista de leis alteradoras. Não é
   regressão deste bloco: medi sem a limpeza nova e a perda é a mesma (35,0 %). É o próximo
   alvo (é o "chunk" do pedido original, e hoje torna irrecuperável tudo que está nesse texto).

### Identidade da base de dev hoje (medido no banco)

`LEI-8080-ESQUEMATIZADA1.pdf` (119 fragmentos, dono 9) **continua com `numero_doc` nulo**: R-9
vale da ingestão para frente e este arquivo não foi reingereido — quem exercitou o caminho novo
no banco foi `Lei 8.213-91.pdf` (2 fragmentos, `numero_doc=8213`, `ano_doc=1991`), além de um
`peticao.pdf` de 1 fragmento usado para medir o isolamento do P1-1. `content_hash` está
preenchido nos 122 fragmentos (backfill da migração).

---

## Bloco 8 — R-24/R-25: o preâmbulo entra no índice, e a medição corrige o plano (2026-10-16, medido em 2026-10-19)

**Pedido:** corrigir o **R-24** — "o chunker descarta 36 % do texto", o item de chunk do pedido
original. O plano de correção (com as decisões D1–D5) está em
[`PLANO_R24_CHUNKER.md`](PLANO_R24_CHUNKER.md); a decisão registrada é o
[ADR-0010](adr/0010-preambulo-e-conteudo-indexavel.md).

### O que entrou

| Item | O que mudou | Como foi verificado |
|:---|:---|:---|
| R-24 | `extrair_paginas` (loader + limpeza R-10 + normalização) passa a ser a base do pipeline e `process_pdf` compõe sobre ela | testes de `test_ingest` com fixture de 3 páginas e dispositivo só na 3ª |
| R-24 | o texto anterior ao 1º dispositivo vira **seção própria, uma por página**, com `tipo_trecho='preambulo'`, `pagina` da página de origem e `artigo = NULL` | fixture sintética: páginas 1–2 aparecem em fragmento marcado, com `pagina` 1 e 2; documento sem dispositivo nenhum segue no caminho antigo (regressão coberta) |
| R-9 | identidade da norma passa a ser lida das **páginas cruas**, não do `join` dos fragmentos | PDF cujo título só existe na página 1 → identidade achada; sem título → cai no nome do arquivo, sem exceção |
| R-25 | `_ARTICLE_START` aceita a grafia ordinal **no início de linha** (`Art. 9º A direção…`) além da forma com pontuação | teste dos dois lados: `Art. 9º A direção…` no começo da linha é marcador; `na forma do art. 2º` no meio **não** é |
| interface | a lista de fontes diz **"trecho de comentário, não é dispositivo"** para `tipo_trecho='preambulo'` | teste de UI com duplo fiel (convenção do repo) |
| operação | reingestão exige **apagar a fonte antes** — com `content_hash` o `ON CONFLICT DO NOTHING` pularia a carga e reportaria 0 fragmentos | feito na base de dev; os 157 fragmentos existem com a identidade nova |

Commits: `9876a7a` (ingestão), `d836fb8` (interface), `738198e` (CI — o snapshot
`docs/legal_test_schema.sql` divergia do schema real e o job ficou vermelho em `d836fb8`).

### Medição na base reingerida (2026-10-19)

Banco `legal_db` (:5439), `phi4-mini:3.8b` @ `LLM_NUM_CTX=8192`, `ollama ps` = **100 % GPU** no
modelo (3,6 GB) e no `nomic-embed-text`, GPU sã (sem `AER`/`Xid`; 46 °C, 420 MiB em uso).

| métrica | antes (119 frag.) | depois (157 frag.) |
|:---|--:|--:|
| chars indexados | 60.584 | **94.563 (+56 %)** |
| composição | 119 `dispositivo` | **141 `dispositivo` + 16 `preambulo`** |
| cobertura do texto limpo (92.037 chars) | 65,8 % | **102,7 %** (excedente = sobreposição do splitter) |
| páginas com amostra de 8-gramas ausente no índice | — | **0 de 65** |
| identidade da norma | 0 de 119 | **157 de 157** (`8080`/`1990`) |

Qualidade — mesmo mini-quiz, mesma bancada:

| critério | antes | depois |
|:---|:---|:---|
| A1 resposta exibida com norma/dispositivo sem lastro | 0 | **0** |
| A2 pergunta fora da base → recusa honesta | 7/7 | **7/7** |
| A4 legítimas respondidas (3 iterações, 18 execuções) | 15/18 | **15/18** |
| latência mediana / p95 (A4) | 7,9 s / 10,6 s | **2,5 s / 12,2 s** |

`medir_portao.py` (uma passagem, 13 casos): A4 5/6 — a recusa é o **d4** (art. 19-B), 1/3 nas
repetições. É instabilidade do modelo de 3,8 B, a mesma do baseline; chunker não conserta isso.

### O que o produto ganhou (a razão do bloco)

A classe de pergunta **conceitual** deixou de receber recusa: *"O que é descentralização no SUS?"*
→ `ok`, 12,8 s, 15 fontes; *"Quais leis alteraram a Lei 8.080? Cite três"* → a lista cronológica
das páginas 3–4 (12.895/2013, 13.097/2015, 12.401/2011). A taxa de acerto do mini-quiz não mudou —
**o ganho é de cobertura**, não de acurácia: pergunta cuja resposta estava fora do índice agora tem
onde ser encontrada.

### O que a medição corrigiu no plano (e um limite que fica)

1. **A fronteira do preâmbulo estava errada.** O plano previa ~34,7 mil chars de preâmbulo nas
   páginas 1–25; a base tem **11.495 chars em 16 fragmentos, páginas 1–8**. Com o **R-25**, o
   primeiro dispositivo real do material está na **página 9** (`Art. 1º Esta lei regula…`), não na
   26 — as páginas 9–25 continuam indexadas, agora dentro de seções de dispositivo (79 dos 141
   têm `artigo`). O plano mediu a fronteira com a regex antiga. **Medir de novo em corpus novo é
   obrigatório.**
2. **`factcheck._load_dispositivos_base` não filtra `tipo_trecho`** (o passo 5 do plano previa que
   preâmbulo não servisse de lastro de dispositivo). Medido nesta base: **efeito zero** — 60
   dispositivos vindos de fragmento `dispositivo`, 60 no total, o preâmbulo não acrescenta nenhum.
   Fica como item de backlog para o corpus oficial, onde comentário é mais numeroso.
3. **O documento envelheceu mais rápido que o commit:** a tabela "Estado atual" deste diário
   continuou dizendo `main` em `cb91fd5` com os blocos 5–7 sem commit depois de `d836fb8` e
   `738198e` já estarem publicados. Corrigida neste bloco — estado se lê do repositório, não do
   resumo da conversa.

### Estado ao fim do bloco

Suíte **279 casos em 14 módulos** verdes sob ambiente limpo (`env -i`); `ruff check .` limpo;
`main` = `origin/main` em `738198e` com CI verde; base de dev com 157 fragmentos, cobertura
completa e identidade preenchida. Artefatos da medição (`app/eval/resultado_a4_rep.json`, novo, e
`resultado_portao.json`, sobrescrito) ficaram **sem commit** neste bloco — publicados depois, em
`bad3c0d`, junto com a documentação (ver "Fechamento do bloco 8" abaixo).

---

## Fechamento do bloco 8 — publicação (2026-10-20)

**Pedido:** fechar o bloco 8 (commitar a documentação, o ADR-0010 e as medições e verificar o CI).

Verificado por execução nesta rodada, na árvore que estava suja desde 2026-10-19:

| Verificação | Como | Resultado |
|:---|:---|:---|
| Links relativos dos documentos mexidos | `scripts/check_doc_links.py` (do skill `legaliz-ai`) | 35 links, todos resolvem |
| Lint | `.venv/bin/python -m ruff check .` | limpo — `All checks passed!` |
| Suíte | `env -i HOME=$HOME PATH=$PATH bash app/run_tests.sh` | **279 casos em 14 módulos**, todos OK |
| CI do GitHub | API `/actions/runs/39529648866/jobs` | **verde nos 4 jobs**: `test`, `lint`, `schema`, `integration` |

Commit **`bad3c0d`** — `docs(bloco-8): ADR-0010 do preâmbulo indexável e medição do bloco`:
`docs/adr/0010-preambulo-e-conteudo-indexavel.md` (novo), `docs/adr/README.md`, `docs/EVOLUCAO.md`,
`docs/BACKLOG.md` (P2-31 registrado), `docs/PLANO_R24_CHUNKER.md`,
`docs/PLANO_REFINAMENTO_RAG.md`, `app/eval/resultado_a4_rep.json` (novo) e
`app/eval/resultado_portao.json` (sobrescrito pela última medição).

Duas observações de ambiente registradas na hora, para não virarem premissa errada:

1. **O banco de dev estava parado** (container `legal-dev-db` saiu ~22 h antes), então nada de
   integração foi exercitado nesta rodada — a verificação de integração que vale aqui é a do CI,
   contra o Postgres descartável. Subir com `make db-dev` antes de qualquer smoke.
2. **O Ollama estava servindo `qwen3:4b` @4096** (resíduo de bancada de medição), enquanto o
   `.env.dev` aponta `phi4-mini:3.8b` @8192. Não é divergência de configuração, mas qualquer
   medição feita agora, sem reiniciar o serviço/limpar a fila, mede outro modelo.

Também corrigida, no mesmo passo, a tabela "Estado atual" — que passou a citar `bad3c0d` — e a
nota de artefatos "não commitados" do bloco 8, que já não era verdade depois do commit.

---

## Bloco 9 — corpus oficial do Planalto (P2-30) e ingestão de texto (2026-10-20)

**Pedido:** pegar o P2-30 ("trazer o corpus oficial e reingerir"), que destrava o R-16 e a
Fase 3.

Decisão de arquitetura registrada em [ADR-0011](adr/0011-corpus-oficial-em-texto.md): o corpus
oficial entra como **texto**, convertido fora da app por `scripts/corpus_planalto.py` (manifesto
com `url`, `sha256` e data de acesso), e `ingest.extrair_paginas` passa a aceitar `.txt`,
paginação sintética em fronteira de parágrafo. Descartados: PDF sintético (fragilidade sem
ganho) e parser de HTML dentro da app (acopla a um formato de fonte).

Código que entrou:

| Arquivo | Mudança |
|:---|:---|
| `scripts/corpus_planalto.py` (novo) | baixa (`--baixar`), converte (`--converter`), ingere (`--ingerir`); `--normas` restringe o escopo |
| `app/ingest.py` | `.txt` em `extrair_paginas`: `_paginar_texto_corrido` (4.000 chars, fronteira de parágrafo) e `_extrair_paginas_de_texto`; sem limpeza de ruído (é de PDF paginado) |
| `app/legal_parser.py` | cabeçalho aceita o ordinal `No` do Planalto com escopo local de caixa (`(?-i:N)o?`) |
| `app/tests/` | +6 casos (`TestCorpusEmTexto` e o caso `DECRETO No 3.048`) |

### O que a execução corrigiu no plano

1. **O maior documento oficial ficava sem identidade.** O Planalto grafa `DECRETO No 3.048`
   (o HTML usa `<u>o</u>`) e `parse_norm_header` devolvia `{'tipo': None, 'numero': None, 'ano':
   None}` — os **689 dispositivos** do Regulamento ficariam sem norma, que é precisamente o
   defeito que o P2-30 veio resolver. A correção exige `N` em caixa alta para aceitar o "o":
   sem esse escopo, "a lei no 8.080" em prosa viraria identidade (testado).
2. **A premissa do card estava parcialmente errada.** O P2-30 dizia que no texto do Planalto o
   par número+ano "vem junto em cada fragmento". Isso vale para o **PDF** do Planalto, não para
   o HTML: medido no texto oficial da 8.080, **1 de 141** fragmentos cita "8.080" no corpo
   (contra 14 de 157 na apostila). O ganho real é o **metadado do documento**: 1.981 de 1.981
   fragmentos com `numero_doc`/`ano_doc`. Registrado no ADR-0011 e no BACKLOG.
3. **Curadoria de corpus tem um efeito que o card não previa: dominância de documento.** O
   Decreto 3.048 é 1.716 de 2.141 fragmentos (80 %) e ocupou **64 dos 90** lugares de top-15
   nas seis perguntas do mini-quiz sobre a 8.080. O `smoke_dev` mostrou o mesmo padrão de forma
   independente. Virou **P2-32** (entra na Fase 3, junto de R-15/R-16).
4. **A apostila saiu da base de dev (decisão do Roberto, 2026-10-20).** Antes de apagar, backup
   dos 157 fragmentos em `.backups/apostila-8080-2026-10-20.json` (94.563 chars; o PDF de origem
   segue em `~/Downloads` e é reingerível). Efeito medido: a dominância do 3.048 **piorou** de 64
   para **74 de 90** lugares de top-15 (a apostila era a única outra fonte da 8.080 no topo), e a
   base ficou em **1.984 fragmentos**. Ou seja: tirar a fonte didática deixa o problema de
   ranking mais visível, não menos — é exatamente o que o P2-32 tem de resolver.

### Medições (todas no banco de dev, 2026-10-20)

| Verificação | Como | Resultado |
|:---|:---|:---|
| Ingestão do corpus | `scripts/corpus_planalto.py --ingerir` | **1.981 fragmentos em ~53 s** (141 da 8.080 em 5,9 s) |
| Identidade | `select count(numero_doc)` por arquivo | **1.981/1.981**; tipos: lei 8080/1990, decreto 3048/1999, emenda 103/2019, lei_complementar 142/2013 |
| Cobertura | chars indexados / chars do `.txt` | 103–107 % (sobreposição do splitter), sem página fora do índice |
| Ruído de apostila | `content ~* 'estrategiaconcursos'` | 0 de 1.981 nos oficiais |
| Portão de resposta (13 casos) | `app/eval/medir_portao.py` | **A2 7/7 recusas corretas**, **A1 0 sem lastro**, **A4 5/6** (d4 recusada) — idêntico ao medido sobre a apostila |
| A4 com repetição (3×) | `app/eval/medir_a4_repetido.py` | **15/18 (83 %)** — o mesmo 15/18 do bloco 8; d4 recusada em 3/3 |
| Faixas de similaridade (R-16) | `1 - (embedding <=> vetor)` no corpus oficial | **dentro 0,761–0,829** × **fora 0,696–0,802** — **sobrepostas**; uma pergunta fora da base (pensão, 0,802) acima de três legítimas |
| Smoke do ambiente | `scripts/smoke_dev.py` | OK (banco, embeddings, recuperação, LLM, fact-check) |

**Leitura honesta:** o corpus oficial **não** mudou o A4 nem a acurácia do mini-quiz — o ganho é
de **base** (fonte oficial, identidade completa, 13× mais conteúdo, sem rodapé de cursinho) e de
**material para calibrar o R-16**. A pergunta que continua falhando (d4: "qual lei incluiu os
arts. 19-Q e 19-R") foi diagnosticada: os fragmentos com a resposta **estão no top-15** (14
fragmentos citam a Lei 12.401, e o 3º e o 4º colocados são exatamente os da 8.080) — quem recusa
é o **portão de suficiência**, porque o dado está em anotação de redação ("(Incluído pela Lei nº
12.401, de 2011)"), não em prosa. Isso é recuperação/portão (Fase 3), não corpus.

### Estado ao fim do bloco

Suíte **285 casos em 14 módulos** verdes sob ambiente limpo; `ruff check .` limpo; integração do
CI reproduzida localmente (14 casos). Base de dev com **1.984 fragmentos**, dos quais 1.981
oficiais com identidade completa; a apostila de medição foi removida com backup em
`.backups/apostila-8080-2026-10-20.json`. **Nada commitado neste bloco** — commit é decisão do
Roberto.

**Nota de concorrência (registrada na hora, porque afeta a leitura dos artefatos):** enquanto este
bloco era fechado, o **P2-32 — criado a partir dele — foi pego pelo dispatcher do Kanban** e passou
a editar `agent.py`, `ranking.py`, `regime.py`, `config.py` e testes no mesmo diretório de
trabalho. A rodada final de `medir_portao.py` desta sessão foi **interrompida de propósito** por
estar medindo código em mutação (saiu A4 4/6, com d5 recusada em cima de 1 trecho — efeito das
mudanças do worker, não da base); `app/eval/resultado_portao.json` foi restaurado ao commit
`bad3c0d` para não guardar artefato contaminado. A medição válida do P2-32 é a que o próprio
worker produz (`app/eval/medir_origem_contexto.py`, `<rotulo> antes` / `depois --hyde`).

### Como retomar este bloco

```bash
cd ~/Documentos/projetos/ia-juridico-cliente
make db-dev
set -a; . ./.env.dev; set +a
.venv/bin/python scripts/corpus_planalto.py --baixar --converter   # reaproveita o manifesto
.venv/bin/python scripts/corpus_planalto.py --ingerir --normas l8080
.venv/bin/python app/eval/medir_portao.py           # 13 casos, ~2 min
.venv/bin/python app/eval/medir_a4_repetido.py      # 3 iterações por pergunta, ~1,5 min
```

---

## Bloco 10 — dominância de documento na recuperação (P2-32, 2026-10-20)

**Pedido:** resolver o P2-32 — o Decreto 3.048 (RPS) tem 86 % dos fragmentos da base e ocupava
quase todo o top-15 em perguntas sobre a Lei 8.080. O card pedia decidir entre limite por arquivo,
diversificação na fusão (MMR) e escopo por norma, **com medição, não por preferência**, e impunha
como aceite: a norma pedida entre os 3 primeiros do contexto, sem regredir o A4 nem o A1.

Decisão registrada em [ADR-0012](adr/0012-escopo-por-norma-e-teto-por-documento.md).

Código que entrou:

| Arquivo | Mudança |
|:---|:---|
| `app/regime.py` | `_parse_norm_reference` / `_extrair_norma` / `_normalizar_ordinais`: a norma que a pergunta **nomeia**, sem exigir artigo; ordinais, mapa de tipos e padrões agora em constantes usadas pelos dois parsers |
| `app/agent.py` | `_buscar_com_escopo` (busca escopada + preenchimento pela busca livre), `_norma_da_pergunta` (respeita `NORM_SCOPE_ENABLED`), teto por documento antes **e** depois do MMR, nos dois caminhos (HyDE e semântico comum); `_semantic_search` aceita `norma` e filtra `numero_doc`/`tipo_doc` no SQL |
| `app/ranking.py` | `_limitar_por_documento` (teto por arquivo com isenção da norma pedida e **sem descartar**) e `_mesma_norma` (identidade pelo metadado) |
| `app/config.py` | `NORM_SCOPE_ENABLED` (default ligado) e `MAX_CHUNKS_PER_DOC` (default 4; 0 desliga) |
| `app/eval/medir_origem_contexto.py` (novo) | medidor da **origem do contexto**: caminho de recuperação, ordem e documento de cada trecho, chars por documento, e o critério do cartão (norma nos 3 primeiros) por grupo |
| `app/tests/` | +14 casos: teto por documento, isenção, `_mesma_norma`, `_parse_norm_reference`, filtro por norma no SQL e o contrato antigo de `_parse_article_reference` |

### O que a execução corrigiu no plano

1. **O mini-quiz media o caminho errado.** Cinco dos seis itens citam "art. N da Lei 8.080" e caem
   na busca por **metadados** (R-15), que já filtra `numero_doc`: medidos sozinhos, dão 6/6 no
   critério **antes** de qualquer conserto. O defeito só aparece em pergunta que não cita artigo
   ("Como a Lei 8.080 trata dos consórcios?"): aí a norma pedida vinha em 9º/10º e 1 em 15
   lugares era dela. O medidor ganhou 7 perguntas sem artigo por causa disso — sem elas, o cartão
   seria fechado com número verde e nada mudado.
2. **MMR não é remédio para dominância de documento** (opção 2 do card, medida e descartada).
   λ = 0,7 / 0,5 / 0,3 / 0,1 sobre o mesmo pool semântico dá **resultado idêntico** (51 lugares da
   norma pedida, mesmas posições): fragmentos de um documento longo têm similaridade ~0,95 entre
   si, a penalidade de redundância vira constante e a ordem não muda.
3. **Teto antes do MMR não basta.** O teto reordena o pool, mas o MMR reordena de novo e traz os
   trechos excedentes de volta — a primeira versão do conserto (teto só antes do MMR) não mudava
   o contexto que o modelo via. Passou a valer também na ordem final.
4. **Dois defeitos de documentação/contrato encontrados no caminho.** A docstring de
   `_parse_article_reference` listava a tupla como `(artigo, número, tipo, parágrafo)`, mas a
   função devolve `(artigo, tipo, número, parágrafo)` — quem lesse a docstring desempacotava
   trocado (corrigido, com `TestParseArticleReferenceCompat` travando o contrato de verdade). E
   `_parse_norm_reference("a Constituição")` não reconhecia a norma sem preposição: passou a
   reconhecer.

### Medições (banco de dev, 2026-10-20, base oficial de 1.984 fragmentos)

A/B pelo mesmo código, alternando só a config (`NORM_SCOPE_ENABLED=false MAX_CHUNKS_PER_DOC=0` =
antes). Instrumento: `app/eval/medir_origem_contexto.py`.

| Verificação | Antes | Depois |
|:---|:---|:---|
| Probes (pergunta que nomeia a norma **sem** artigo) com a norma entre os 3 primeiros | **4 de 7** (p3 em 5º, p4 em 4º, p5 em 10º) | **7 de 7** |
| Lugares da norma pedida no top-15 (probes) | 51 de 105 | **90 de 105** |
| Mini-quiz (6 itens) com a norma entre os 3 primeiros | 6 de 6 (via metadados) | 6 de 6 |
| Lugares da norma pedida no top-15 (mini-quiz) | 14 de 26 | 24 de 26 |
| Maior documento no contexto | d3048 = 50 % dos chars | l8080 = 72 % (é a norma pedida) |
| Caminho completo HyDE + RRF (probes) | — | **7 de 7**, 92 de 105 |
| A4 repetido (3 iterações × 6 perguntas) | 13 de 18 | 13 de 18 |
| A1 exibidas com norma/dispositivo sem lastro | 0 | **0** |
| A2 recusas corretas nas perguntas fora da base | 7 de 7 | 7 de 7 |

Uma rodada intermediária do A4 deu **12 de 18**: a diferença estava em **d5**, cuja entrada é
idêntica nos dois lados (1 trecho, 372 chars, via metadados — caminho que este bloco não toca). A
repetição devolveu 13 de 18, e o d5 fica como está: é o **R-15** (a via de metadados devolve
direto e entrega 1 trecho para "quais leis foram revogadas pelo art. 55").

Suíte **299 casos em 14 módulos** verdes sob ambiente limpo (`env -i`); `ruff check .` limpo.

### Estado ao fim do bloco

Base de dev de **1.984 fragmentos** (só corpus oficial, sem a apostila). O cartão deixa de ser
opção e vira comportamento padrão (`NORM_SCOPE_ENABLED=true`, `MAX_CHUNKS_PER_DOC=4`), com os dois
desligáveis por config para A/B. **Nada commitado neste bloco** — commit é decisão do Roberto.

**Nota de concorrência (registrada na hora):** este bloco rodou em paralelo com o fechamento do
bloco 9, no mesmo diretório de trabalho. O worker do bloco 9 removeu a apostila da base **no meio**
desta medição (2.141 → 1.984 fragmentos) e interrompeu a própria rodada de `medir_portao` por estar
medindo código em mutação — a nota dele está no bloco 9. Consequência prática: **todas** as medidas
"antes" deste bloco foram refeitas depois da remoção, com a base registrada em cada artefato
(`resultado_origem_*.json` traz o retrato da base no campo `base`), para que antes e depois não
falem de bases diferentes. O A4 repetido também foi medido nas duas pontas depois disso.

### Como retomar este bloco

```bash
cd ~/Documentos/projetos/ia-juridico-cliente
make db-dev
set -a; . ./.env.dev; set +a
# A/B do ranking (rápido, sem LLM): mesma base, mesmo código
NORM_SCOPE_ENABLED=false MAX_CHUNKS_PER_DOC=0 \
  .venv/bin/python app/eval/medir_origem_contexto.py --rotulo antes
.venv/bin/python app/eval/medir_origem_contexto.py --rotulo depois          # + --hyde p/ o caminho completo
# produto (LLM): ~2 min cada
.venv/bin/python app/eval/medir_portao.py
.venv/bin/python app/eval/medir_a4_repetido.py
```

---

## Bloco 11 — o peso por regime sai do caminho (ADR-0013, 2026-10-20)

**Pedido:** revisar o `app/regime.py` — a suspeita era que a regra de "regime jurídico", nascida
para desambiguar RPPS × RGPS, tivesse virado um conjunto de pesos privilegiados que já não paga o
custo, e que devesse ser desativada ou excluída.

Decisão registrada em [ADR-0013](adr/0013-retirada-do-peso-por-regime.md): **desligada por padrão**
(`REGIME_BOOST_ENABLED=false`), com a função preservada atrás da flag como instrumento de A/B.
`_parse_article_reference` e `_metadata_search` **não** foram tocados — são busca determinística por
artigo (R-15), não peso por regime.

### O que a medição mostrou (e a correção de rota)

| Experimento | Com peso | Sem peso |
|:---|:---:|:---:|
| Posição da norma pedida no top-15 (11 perguntas) | — | — | **empate em 11/11** |
| A4 do mini-quiz (6 × 3 iterações) | 12/18 | 12/18 |
| A4 nas perguntas de RGPS (4 × 3) | 6/12 | **7/12** |
| Resposta cita a norma esperada (RGPS) | **4/12** | 1/12 |
| Normas no contexto — "cota do salário-família" | **só** decreto 3048 | 3048 + emenda 103 |
| Normas no contexto — "dependentes de pensão por morte" | **só** decreto 3048 (15/15) | 3048 + EC 103 + LC 142 |

O 4/12 contra 1/12 parecia defender o peso — e é **artefato**: com o peso, o contexto fica 15/15 de
um único documento, e o modelo cita o único documento que recebeu. O peso **estreita o contexto** e
expulsa a EC 103 e a LC 142, que é a mesma dominância de documento que o bloco 10 acabou de
corrigir, reintroduzida por outra porta.

Duas armadilhas de medição que custaram uma rodada cada:

1. **Testar o peso no mini-quiz não prova nada.** As seis perguntas são sobre a Lei 8.080, e para
   saúde o perfil inferido é vazio (`{'preferred': [], 'excluded': []}`) — desligar o peso não podia
   mudar resultado. Foi por isso que a segunda rodada usou perguntas de RGPS, que ativam o perfil.
2. **Métrica de "citação" sozinha engana.** Ela mede o que o modelo viu, não o que ele deveria ver.
   Só a inspeção do contexto recuperado (normas presentes com e sem peso) mostrou o mecanismo.

### Estado ao fim do bloco

Suíte **301 casos em 14 módulos** verdes (`env -i`), `ruff check .` limpo. Validado no produto:
`agent.REGIME_BOOST_ENABLED` é `False` sem variável de ambiente, o contexto de RGPS volta a trazer
EC 103 e LC 142, e nenhum documento recebe `regime_score`. Dívida aberta em **P2-33**: nomes por
extenso ("Lei Orgânica da Saúde") não são reconhecidos pelo escopo por norma — agora sem a muleta do
peso, é o próximo buraco da recuperação.

---

## Pendências (detalhe e critério de aceite no BACKLOG)

| Item | Onde | Por que ainda não foi feito |
|:---|:---|:---|
| **P0-5** TLS + fechar a porta 5439 | infra do cliente | depende do servidor/proxy do cliente |
| **P0-6** rotacionar credenciais | operação | as chaves já circularam em HTTP e com o banco exposto |
| **P1-1** fact-check escopado por dono e com memória limitada | `app/factcheck.py` | ✅ **feito no bloco 7** (cache por dono + teto de linhas/caracteres) |
| **R-24** chunker descartava 36 % do texto (antes do 1º `Art. N`) | `app/ingest.py` | ✅ **feito no bloco 8** (ADR-0010): preâmbulo indexado e rotulado, 92.037 → 94.563 chars, 0 de 65 páginas fora do índice |
| **R-25** grafia ordinal sem pontuação não reconhecida | `app/ingest.py` | ✅ **feito no bloco 8**: âncora de linha na regex, teste dos dois lados |
| **P1-2** estado global de LLM entre sessões | `app/agent.py` | qualquer usuário troca o modelo de todos |
| **P1-6** PDF escaneado falha em silêncio | `app/ingest.py` | precisa de mensagem de erro (OCR é decisão de produto) |
| **P1-8** prompt injection indireta | `app/prompts/` | mitigação a definir com o cliente |
| **P1-9** falsos positivos do fact-check | `app/factcheck.py` | **reduzido na Fase 1** (bloco 6): a seção obrigatória de regime saiu do prompt e `sem_fonte` virou aviso; o resto é formato de dispositivo ("artigo 25" vs "Art. 25.") |
| P2 (14 itens) | vários | melhorias e riscos aceitáveis no curto prazo |

### Decisões operacionais em aberto

1. **Nada pendente de publicação**: `main` = `origin/main` em `bad3c0d` (o bloco 8 — documentação,
   ADR-0010 e os dois arquivos de resultado da medição — foi commitado e publicado em 2026-10-20,
   com CI verde nos 4 jobs). Árvore de trabalho limpa.
2. **Rotação do login de desenvolvimento**: o usuário `dev@legaliz.local` é criado pelo
   smoke test com senha conhecida; trocar pelo painel quando o ambiente for compartilhado.
3. **Dívida pequena registrada no bloco 8**: `factcheck._load_dispositivos_base` não filtra
   `tipo_trecho` (preâmbulo em tese serve de lastro de dispositivo). Efeito medido na base de dev:
   zero. Entra no backlog para a chegada do corpus oficial.
