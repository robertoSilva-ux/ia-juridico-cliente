#!/usr/bin/env bash
# Sobe a aplicação NATIVA (sem container) para desenvolvimento.
#
# Arranjo: banco em container podman (scripts/db-dev.sh) + Ollama nativo no host.
# Ver docs/AMBIENTE_DEV.md — em particular por que o ensaio com o stack completo
# (Docker Compose, com os limites de memória reais) continua sendo necessário.
#
# Uso: bash scripts/dev.sh
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env.dev ] || { echo "✘ falta o .env.dev — veja docs/AMBIENTE_DEV.md"; exit 1; }

PY="${PYTHON:-.venv/bin/python3}"
[ -x "$PY" ] || { echo "✘ falta o venv .venv — veja docs/AMBIENTE_DEV.md"; exit 1; }

# O container recebe o .env via `env_file`; rodando nativo, quem carrega é esta
# linha (por isso o .env.dev precisa ter DATABASE_URL/OLLAMA_BASE_URL apontando
# para localhost, e não para os nomes de serviço do compose).
set -a; . ./.env.dev; set +a

# Banner com o DSN mascarado: nada de senha aparecendo em log de terminal.
echo "banco:  $(printf '%s' "$DATABASE_URL" | sed -E 's#://[^:]+:[^@]+@#://***@#')"
echo "ollama: $OLLAMA_BASE_URL"
if ! curl -sf "$OLLAMA_BASE_URL/api/version" >/dev/null 2>&1; then
  echo "⚠ Ollama não está respondendo em $OLLAMA_BASE_URL — suba com: ~/.local/bin/ollama serve &"
fi

cd app
exec ../"$PY" -m streamlit run main.py --server.port="${STREAMLIT_SERVER_PORT:-8501}"
