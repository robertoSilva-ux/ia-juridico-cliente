#!/usr/bin/env bash
# Runner dos testes do Legaliz.ai.
#
# Por que um módulo por processo: os testes mockam `psycopg2`/`pgvector`/
# `langchain*` em `sys.modules` no import (padrão documentado em docs/TESTING.md).
# Rodar vários no mesmo processo faz os mocks de um arquivo colidirem com os do
# outro.
#
# A descoberta é DINÂMICA (todos os tests/test_*.py): a versão anterior tinha uma
# lista fixa de 4 módulos, então 5 arquivos de teste — incluindo test_agent.py, o
# maior da suíte — não eram executados por nenhum runner, Makefile ou CI.
#
# Uso: bash run_tests.sh [-v]     (a partir de app/ ou de qualquer lugar)
set -uo pipefail

cd "$(dirname "$0")" || exit 1     # app/
VERBOSE="${1:-}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 não encontrado no PATH." >&2
  exit 1
fi

mapfile -t MODULES < <(python3 -c "
import pathlib
print('\n'.join(sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py'))))
")

if [ "${#MODULES[@]}" -eq 0 ]; then
  echo "Nenhum módulo de teste encontrado em app/tests/." >&2
  exit 1
fi

fails=()
total_tests=0
for m in "${MODULES[@]}"; do
  echo "=== tests.${m} ==="
  if out=$(python3 -m unittest "tests.${m}" ${VERBOSE:+-v} 2>&1); then
    echo "$out" | tail -n 3
  else
    # Falhou: mostra o suficiente para diagnosticar, não a saída inteira.
    echo "$out" | tail -n 40
    echo ">>> FALHA em tests.${m}"
    fails+=("$m")
  fi
  ran=$(echo "$out" | sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p')
  total_tests=$((total_tests + ${ran:-0}))
  echo
done

echo "----------------------------------------------------------------"
echo "Total de casos executados: ${total_tests} em ${#MODULES[@]} módulos"
if [ "${#fails[@]}" -gt 0 ]; then
  echo ">>> ${#fails[@]} módulo(s) com falha: ${fails[*]}"
  exit 1
fi
echo ">>> Todos os módulos de teste passaram."
