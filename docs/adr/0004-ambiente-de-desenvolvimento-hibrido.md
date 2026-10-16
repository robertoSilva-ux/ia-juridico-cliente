# ADR-0004 — Ambiente de desenvolvimento híbrido, com ensaio de paridade obrigatório

- **Status:** aceito
- **Data:** 2026-10-16
- **Detalhamento:** [`../AMBIENTE_DEV.md`](../AMBIENTE_DEV.md)

## Contexto

O produto roda no cliente como três serviços em Docker Compose (`db` com pgvector,
`ollama`, `app`). Na máquina de desenvolvimento não havia Docker, e a pergunta foi se
valeria desenvolver com os containers desde o início ou localmente e containerizar só no
release. As três camadas têm custos e ganhos de paridade bem diferentes:

- **banco**: a versão do Postgres e da extensão mudam comportamento (recall de índice
  vetorial, por exemplo). Medido: `pgvector/pgvector:pg16` traz Postgres 16.15 + vector
  0.8.7, enquanto a imagem `ankane/pgvector` usada no compose do cliente está numa série
  antiga;
- **Ollama**: a aplicação fala HTTP com ele, então a interface é estável. Em dev, o
  container custa imagem CUDA pesada e, no compose, `OLLAMA_KEEP_ALIVE=5m` **descarrega o
  modelo** entre perguntas — péssimo para iterar prompt;
- **aplicação**: o `Dockerfile` copia o código no build (sem bind mount), ou seja cada
  edição viraria rebuild.

## Decisão

Desenvolvimento **híbrido**:

1. **Banco em container** desde o primeiro dia — é onde a paridade importa e o custo é
   nulo. Na máquina de dev usa-se **podman rootless** (sem sudo, já presente no Fedora);
   o engine do cliente continua sendo Docker, e o que precisa coincidir é a versão do
   Postgres + pgvector.
2. **Ollama nativo**, como serviço de sistema, apontando para o mesmo modelo de produção
   (`phi4-mini:3.8b`) e o mesmo modelo de embeddings.
3. **Aplicação nativa** em venv (Python 3.11, a mesma versão do container), com `make dev`
   carregando um `.env.dev` que aponta para `localhost`.
4. **Ensaio de paridade obrigatório antes de release**, com Docker Compose, porque o modo
   nativo esconde exatamente o que pode quebrar no cliente: `mem_limit: 512m` do serviço
   `app` (onde o P1-1 aparece), `OLLAMA_KEEP_ALIVE`, `env_file`, portas publicadas e a
   ausência de TLS (P0-5).

## Consequências

- Iteração rápida (reload de código, sem rebuild de imagem) e sem sudo para subir o banco.
- Divergências ficam limitadas a onde são conhecidas e checadas no ensaio — em vez de
  espalhadas por todo o desenvolvimento.
- Custo aceito: dois caminhos de execução documentados, e a disciplina do ensaio de
  paridade (que é um item de checklist, não um teste automatizado — o CI cobre schema e
  integração, não o compose completo).
- O driver NVIDIA continua sendo pré-requisito do host nos dois modos: o container apenas
  consome o driver.

## Alternativas consideradas

1. **Tudo em containers desde já** — descartado para o dia a dia pelo custo de iteração
   (rebuild por edição) e pela fricção de GPU/imagem CUDA; o que ele oferece de paridade é
   obtido no ensaio.
2. **Tudo nativo, inclusive Postgres do sistema** — descartado: divergência de versão e de
   compilação da extensão vetorial é a fonte de bug mais provável neste produto, e é a
   camada mais barata de containerizar.
3. **Instalar Docker na máquina de dev** — adiado: podman rootless atende o banco hoje; o
   Docker entra quando o ensaio de paridade exigir o mesmo engine do cliente.
