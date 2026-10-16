# ADR-0005 — Dependências pinadas com lock e verificação automatizada obrigatória

- **Status:** aceito
- **Data:** 2026-10-16
- **Achados relacionados:** P1-4 e P1-5 em [`../REVISAO_SEGURANCA.md`](../REVISAO_SEGURANCA.md)

## Contexto

Duas situações medidas:

- `app/requirements.txt` não fixava versão nenhuma. Um `docker compose build` no servidor
  do cliente resolveria pacotes novos sem nenhuma mudança de código — e a
  `streamlit-authenticator`, que assina o cookie de sessão, mudou de API entre as séries
  0.3 e 0.4. Além disso, `requests` (usado em `ollama_utils.py`), `langchain-core` e
  `langchain-text-splitters` eram **importados e não declarados**, funcionando por
  dependência transitiva.
- A verificação automatizada não verificava: o CI rodava só `flake8` com
  `--select=E9,F63,F7,F82` (não o `ruff` configurado no `pyproject.toml`) e **nunca** a
  suíte; `make test` apontava para arquivos que não existiam; o runner tinha lista fixa de
  4 módulos, então **5 dos 9 arquivos de teste nunca eram executados por ninguém**
  (incluindo o maior deles).

## Decisão

1. **Pins explícitos** em `app/requirements.txt` para todas as dependências (runtime e
   ferramenta de lint), resolvidos em Python 3.11 — a mesma versão do container — mais um
   `requirements.lock.txt` com a resolução completa, para reprodução byte a byte.
2. Dependências **importadas passam a ser declaradas** (fim do "funciona por sorte").
3. **Runner único** (`app/run_tests.sh`) com descoberta dinâmica de todos os
   `tests/test_*.py`, um módulo por processo (exigência do padrão de mocks do projeto), e
   total de casos no resumo. `make test` roda no container; `make test-local`, no host.
4. **CI com quatro jobs**: lint (`ruff`, o linter declarado), testes, integração com
   Postgres pgvector real, e verificação de schema — este último aplica `init.sql` e a
   migração **duas vezes** (idempotência) e confere invariantes de segurança, incluindo se
   o `ON CONFLICT` da ingestão casa com o índice vigente.

## Consequências

- Rebuild no cliente é reproduzível; atualizar dependência passa a ser ato deliberado.
- A suíte roda de fato, e a cobertura de execução acompanha o número de arquivos de teste
  (não depende de alguém lembrar de editar uma lista).
- O job de schema pega justamente a classe de erro que passou nesta revisão: o desalinhamento
  entre o índice único e o `ON CONFLICT` usado pela aplicação.
- Custo aceito: o CI ficou mais lento (instala as dependências de runtime e sobe um banco
  com pgvector) e o lock precisa ser regenerado quando se atualiza algo.

## Alternativas consideradas

1. **Pin só das dependências diretas, sem lock** — parcialmente adotado (o
   `requirements.txt` tem os pins diretos); o lock existe porque a resolução transitiva é
   onde a quebra costuma aparecer.
2. **Continuar com `flake8` no CI** — descartado: era verde sem cobrir as regras que o
   projeto declara, o que dá falsa sensação de proteção.
3. **Rodar a suíte inteira num só processo** — descartado: colide os mocks de
   `sys.modules` (documentado em `docs/TESTING.md`).
