# Legaliz.ai — Roadmap de Implementação (loop: task → testes → commit → próxima)

Branch ativa: `main` (commits diretos desde o merge do PR #1).

## Status
| # | Task | Prioridade | Status |
|---|------|-----------|--------|
| 0 | **Push branch citacoes + PR p/ main** (commits citação `361c99b` + dedup `ae12dfb`) | Alta | ✅ concluída (PR #1) |
| 1 | **Re-ranking / contextual compression (MMR)** — filtra noise da doutrina/notas de rodapé. Fonte: Kimothi + Auffarth | Alta | ✅ concluída (commit `b37921e`, via PR #1) |
| 2 | **Self-consistency / fact-check** — anti-alucinação estrutural (além do prompt). Fonte: Auffarth | Alta | ✅ concluída (commit `532c583`, direto na main) |
| 3 | **Query expansion / HyDE** — melhora recall léxico jurídico. Fonte: Kimothi | Média | ✅ concluída (commit `0e15d0b`, direto na main) |
| 4 | **Setar `LLM_MODEL` no `.env`** + rebuild container app (ativa dedup no ingest + resposta sem config manual) | Baixa | ✅ concluída (commit direto na main) |
| 5 | Reavaliar escopo de user do Legaliz (busca por user_id) se necessário | Baixa | ⏳ pendente |

## Ordem sugerida de execução
1. **Task 0** (push + PR): destrava o que já está pronto, evita conflito futuro.
2. **Task 1** (re-ranking): maior ganho visível no retrieval jurídico; base p/ as demais.
3. **Task 2** (fact-check): valor crítico em direito (não citar lei inexistente). 🟢 PRÓXIMA foi concluída.
4. **Task 3** (HyDE): complementa recall após re-ranking. 🟢 concluída.
5. **Task 4** (env/rebuild): última pendente; pode ser feito em paralelo. 🟢 concluída.

> ⚠️ Desde o merge do PR #1, **commits vão direto na `main`** (Roberto pediu para pular PR/merge).

## Notas técnicas
- Token GitHub em `~/.config/legalizai-github.env` (permissão 600, `GITHUB_TOKEN`). Escopos: repo, workflow, gist. Abre PRs via API.
- LangChain é v1.2 (ecossistema dos livros, branch `v1` do repo benman1/generative_ai_with_langchain).
- Base de referência dos livros de RAG indexada no Temporal Wolf (Kimothi `A Simple Guide to RAG`, Auffarth `RAG The Seminal Papers`).
- Testes: rodam por arquivo em processo separado (`python3 -m unittest tests.test_<nome>` de `app/`). **83 verdes** (agent 34, legal_parser 21, ingest 8, management 8, auth 12).
- Padrão de mock: `sys.modules` collide — cada arquivo de teste isolado.
