#!/usr/bin/env bash
# Wrapper de compatibilidade.
#
# O runner passou a viver em `app/run_tests.sh`: ele precisa estar DENTRO da
# imagem, cujo build context é `app/` (o Dockerfile faz `COPY . .` a partir de
# app/), para poder ser executado no container — que é o ambiente real. Este
# caminho continua funcionando para quem já o chamava.
set -euo pipefail
exec bash "$(dirname "$0")/../app/run_tests.sh" "$@"
