#!/bin/bash
set -euo pipefail

# Cores
VERDE='\033[0;32m'; AMARELO='\033[1;33m'; VERMELHO='\033[0;31m'; RESET='\033[0m'
ok()  { echo -e "${VERDE}✓${RESET} $1"; }
warn(){ echo -e "${AMARELO}⚠${RESET} $1"; }
fail(){ echo -e "${VERMELHO}✘${RESET} $1"; exit 1; }

SERVICO="IA-Jurídico"
RAIZ="/opt/ia-juridico"
DIRS=(
  "$RAIZ"
  "/srv/ia-juridico/documentos"
  "/srv/ia-juridico/vetorial"
  "/srv/ia-juridico/modelos"
  "/srv/ia-juridico/backups"
  "/var/log/ia-juridico"
)

echo "========================================================"
echo "  🚀 Setup — $SERVICO"
echo "========================================================"
echo ""

# 0. Verificar root
if [ "$(id -u)" -ne 0 ]; then
  fail "Execute como root (sudo ./setup.sh)"
fi

# 1. Verificar Docker
echo "--- Pré-requisitos ---"
if command -v docker &>/dev/null; then
  ok "Docker instalado"
else
  warn "Docker não encontrado. Instalando..."
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  systemctl enable --now docker
  ok "Docker instalado"
fi

# 2. Verificar NVIDIA GPU (Container Toolkit)
if lspci 2>/dev/null | grep -qi "nvidia"; then
  echo "  GPU NVIDIA detectada."
  if command -v nvidia-ctk &>/dev/null || nvidia-smi &>/dev/null; then
    ok "NVIDIA Container Toolkit OK (ou driver host presente)"
  else
    warn "GPU NVIDIA detectada mas sem Container Toolkit."
    warn "  Se quiser aceleração por GPU: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
    warn "  Continuando em modo CPU (mais lento, funcional)."
  fi
else
  echo "  Nenhuma GPU NVIDIA detectada — rodando em CPU."
fi

# 3. Criar estrutura de diretórios
echo ""
echo "--- Estrutura de diretórios ---"
for d in "${DIRS[@]}"; do
  mkdir -p "$d"
  ok "$d"
done

# Ajustar permissões do diretório vetorial (UID do postgres = 999)
chown 999:999 /srv/ia-juridico/vetorial 2>/dev/null || true

# 4. Copiar projeto
echo ""
echo "--- Código-fonte ---"
ORIGEM="$(cd "$(dirname "$0")" && pwd)"
if [ "$ORIGEM" != "$RAIZ" ]; then
  cp -r "$ORIGEM"/* "$ORIGEM"/.[!.]* "$RAIZ"/ 2>/dev/null || true
  ok "Código copiado para $RAIZ"
  cd "$RAIZ"
else
  ok "Já estamos em $RAIZ"
fi

# 5. .env
echo ""
echo "--- Configuração ---"
ENV_FILE="$RAIZ/.env"
if [ ! -f "$ENV_FILE" ]; then
  if [ -f ".env.cliente" ]; then
    cp .env.cliente "$ENV_FILE"
  elif [ -f ".env.example" ]; then
    cp .env.example "$ENV_FILE"
  fi
  warn ".env criado a partir do template."
  warn "  EDITE $ENV_FILE com a senha real do banco antes de continuar!"
  echo "  Pressione ENTER após revisar, ou Ctrl+C para cancelar."
  read -r
else
  ok ".env já existe"
fi

# 6. Subir containers
echo ""
echo "--- Containers ---"
docker compose up -d --build
ok "Containers em execução"

# 7. Aguardar serviços
echo ""
echo "--- Aguardando serviços ---"
echo "  Ollama..."
until docker exec legal-ollama ollama list &>/dev/null 2>&1; do
  sleep 3
done
ok "Ollama operacional"

echo "  Banco de dados..."
until docker exec legal-db pg_isready -U "${POSTGRES_USER:-user}" -d "${POSTGRES_DB:-legal_db}" &>/dev/null; do
  sleep 2
done
ok "PostgreSQL operacional"

echo "  Aplicação..."
until curl -sf http://localhost:8501/_stcore/health &>/dev/null; do
  sleep 5
done
ok "Streamlit operacional"

# 8. Modelos
echo ""
echo "--- Modelos de IA ---"
for modelo in "nomic-embed-text" "${LLM_MODEL:-phi4-mini:3.8b}"; do
  if docker exec legal-ollama ollama list 2>/dev/null | grep -q "$modelo"; then
    ok "Modelo '$modelo' já instalado"
  else
    echo "  Baixando $modelo..."
    docker exec legal-ollama ollama pull "$modelo"
    ok "Modelo '$modelo' instalado"
  fi
done

# 9. Admin inicial
echo ""
echo "--- Admin inicial ---"
docker exec legal-app python init_admin.py 2>/dev/null && ok "Admin criado" || warn "Admin pode já existir (ignore se for repetição)"

echo ""
echo "========================================================"
echo "  🎉 Setup concluído!"
echo "  👉 Acesse: http://localhost:8501"
echo "  👤 Login: admin@legaliz.ai / admin123"
echo "========================================================"