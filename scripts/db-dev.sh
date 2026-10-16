#!/usr/bin/env bash
# Banco de desenvolvimento: PostgreSQL 16 + pgvector em container PODMAN ROOTLESS.
#
# Não usa sudo e não usa Docker de propósito: o motor não é o que dá diferença de
# comportamento aqui — o que importa é a VERSÃO do Postgres e do pgvector, que é
# a mesma do cliente (`pgvector/pgvector:pg16`, extensão vector 0.8.x). Ver
# docs/AMBIENTE_DEV.md para o raciocínio completo.
#
# Uso: bash scripts/db-dev.sh [start|stop|rm|psql|status]
set -euo pipefail
cd "$(dirname "$0")/.."

NOME=legal-dev-db
IMAGEM=docker.io/pgvector/pgvector:pg16    # nome completo: podman rootless não resolve short-name
PORTA=5439                                  # mesma convenção do compose do cliente
SENHA=dev_local_senha                       # senha de um container local, descartável

case "${1:-start}" in
  start)
    if podman container exists "$NOME" 2>/dev/null; then
      podman start "$NOME" >/dev/null 2>&1 || true
      echo "banco de dev já existia — iniciado"
    else
      podman run -d --name "$NOME" \
        -e POSTGRES_USER=user -e POSTGRES_PASSWORD="$SENHA" -e POSTGRES_DB=legal_db \
        -p "$PORTA:5432" \
        -v "$PWD/database/init.sql:/docker-entrypoint-initdb.d/init.sql:ro,Z" \
        -v legal-dev-pgdata:/var/lib/postgresql/data \
        "$IMAGEM" >/dev/null
      echo "banco de dev criado (schema aplicado pelo database/init.sql)"
    fi
    for _ in $(seq 1 40); do
      podman exec "$NOME" pg_isready -U user -d legal_db >/dev/null 2>&1 && break
      sleep 1
    done
    podman exec "$NOME" pg_isready -U user -d legal_db
    echo "pronto em localhost:$PORTA (db legal_db) — credenciais no .env.dev"
    ;;
  stop)   podman stop "$NOME" ;;
  rm)     podman rm -f "$NOME" 2>/dev/null || true; podman volume rm legal-dev-pgdata 2>/dev/null || true
          echo "container e volume do banco de dev removidos" ;;
  psql)   podman exec -it "$NOME" psql -U user -d legal_db ;;
  status) podman ps -a --filter "name=$NOME" ;;
  *)      echo "uso: $0 [start|stop|rm|psql|status]"; exit 2 ;;
esac
