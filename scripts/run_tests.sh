#!/usr/bin/env bash
# Executa os testes unitários do Legaliz.ai — cada arquivo em processo separado.
#
# Por que por arquivo? Os testes mockam psycopg2/pgvector em sys.modules no import.
# Rodar vários arquivos no mesmo processo causa colisão dos mocks.
set -uo pipefail

cd "$(dirname "$0")/../app"

UNIT_TESTS=(
  tests.test_legal_parser
  tests.test_ingest
  tests.test_management
  tests.test_auth
)

fails=0
for t in "${UNIT_TESTS[@]}"; do
  echo "=== ${t} ==="
  if ! python3 -m unittest "${t}" 2>&1 | tail -n 6; then
    echo ">>> FALHA em ${t}"
    fails=$((fails + 1))
  fi
  echo
done

if [ "$fails" -gt 0 ]; then
  echo ">>> ${fails} módulo(s) com falha."
  exit 1
fi
echo ">>> Todos os testes unitários passaram."
