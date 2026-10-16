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
| Branch / remoto | `main` local em `cb91fd5` + o trabalho dos blocos 5, 6 e 7 (não commitado — commit é decisão do Roberto) |
| Suíte | **268 casos em 14 módulos** verdes, também sob ambiente limpo (`env -i HOME=$HOME PATH=$PATH bash app/run_tests.sh`, medido 2026-10-16) + 14 de integração contra Postgres real |
| Lint | `ruff check .` limpo — **precisa ser o do venv**: fora dele o comando não existe (`.venv/bin/python -m ruff check .`) |
| Ambiente de dev | montado e funcionando: banco em podman (5439), Ollama em serviço + GPU, `.venv` 3.11, `make dev` |
| Modelo padrão | `phi4-mini:3.8b` @ `LLM_NUM_CTX=8192` — decisão registrada no ADR-0008 |
| Garantia de lastro | três barreiras (suficiência → lastro no fragmento citado → portão de exibição) — ADR-0009 |
| Base de dev | 122 fragmentos em 3 arquivos: `LEI-8080-ESQUEMATIZADA1.pdf` (119, dono 9) + 2 artefatos das medições de hoje (`Lei 8.213-91.pdf`, 2 fragmentos globais, **inauguram o R-9 no banco**: vieram com `numero_doc=8213`; `peticao.pdf`, 1 fragmento, criado para medir o isolamento do P1-1). `content_hash` preenchido nos 122 (backfill). **Os 119 fragmentos antigos seguem com `numero_doc`/`ano_doc`/`pagina`/`ordem` nulos** — R-9/R-13 valem da ingestão para frente, e o PDF da apostila não existe mais na máquina: a primeira carga que exercita isso com dado real é a do corpus oficial |
| Bloqueadores de produção | **P0-5** (TLS + fechar a porta do banco) e **P0-6** (rotacionar credenciais que já circularam) — só o cliente pode executar |

### Como retomar

```bash
cd ~/Documentos/projetos/ia-juridico-cliente
git log --oneline -5                 # onde paramos
git status --short                   # blocos 5, 6 e 7 seguem sem commit
make db-dev                          # religa o banco de dev (depois de reboot)
set -a; . ./.env.dev; set +a
.venv/bin/python scripts/smoke_dev.py   # o ambiente está de pé?
cat docs/PLANO_REFINAMENTO_RAG.md     # Fases 1 e 2 fechadas; Fase 3 (recuperação) é a próxima
```

Leitura rápida: **Fase 1 e Fase 2 do plano estão executadas** (blocos 6 e 7). O que sobra do pedido
"resposta 100 % fundamentada ou recusa honesta" é **Fase 3** (recuperação: R-15, R-16, R-18) — e o
**corpus oficial do Planalto** (P2-30), que é ao mesmo tempo a maior alavanca de qualidade restante e
o pré-requisito para o portão relativo (R-16) ter o que calibrar. **P1-2** (estado global do LLM) vem
na Fase 4.

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

## Pendências (detalhe e critério de aceite no BACKLOG)

| Item | Onde | Por que ainda não foi feito |
|:---|:---|:---|
| **P0-5** TLS + fechar a porta 5439 | infra do cliente | depende do servidor/proxy do cliente |
| **P0-6** rotacionar credenciais | operação | as chaves já circularam em HTTP e com o banco exposto |
| **P1-1** fact-check escopado por dono e com memória limitada | `app/factcheck.py` | ✅ **feito no bloco 7** (cache por dono + teto de linhas/caracteres) |
| **R-24** chunker descarta 36 % do texto (antes do 1º `Art. N`) | `app/ingest.py` | medido no PDF real; é o próximo alvo da Fase 2, com o corpus oficial |
| **P1-2** estado global de LLM entre sessões | `app/agent.py` | qualquer usuário troca o modelo de todos |
| **P1-6** PDF escaneado falha em silêncio | `app/ingest.py` | precisa de mensagem de erro (OCR é decisão de produto) |
| **P1-8** prompt injection indireta | `app/prompts/` | mitigação a definir com o cliente |
| **P1-9** falsos positivos do fact-check | `app/factcheck.py` | **reduzido na Fase 1** (bloco 6): a seção obrigatória de regime saiu do prompt e `sem_fonte` virou aviso; o resto é formato de dispositivo ("artigo 25" vs "Art. 25.") |
| P2 (14 itens) | vários | melhorias e riscos aceitáveis no curto prazo |

### Decisões operacionais em aberto

1. **Publicar ou não** os commits `42dc943` e `f432730` (`git push origin main`) — estão
   locais.
2. **Rotação do login de desenvolvimento**: o usuário `dev@legaliz.local` é criado pelo
   smoke test com senha conhecida; trocar pelo painel quando o ambiente for compartilhado.
