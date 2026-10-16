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
  warn "  EDITE $ENV_FILE antes de continuar. Os templates trazem PLACEHOLDER (***),"
  warn "  e o sistema não sobe com eles: POSTGRES_PASSWORD, DATABASE_URL,"
  warn "  ADMIN_PASSWORD e COOKIE_KEY precisam de valores REAIS."
  warn "  Gere a COOKIE_KEY com: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\""
  echo "  Pressione ENTER após revisar, ou Ctrl+C para cancelar."
  read -r
else
  ok ".env já existe"
fi

# 5b. Validação de configuração de segurança — falha ANTES de subir os containers.
# O sistema não deve iniciar com senha de banco placeholder (o app não conectaria
# de forma confusa), nem sem ADMIN_PASSWORD (admin adivinhável) nem sem COOKIE_KEY
# (cookie de sessão forjável: ver docs/REVISAO_SEGURANCA.md, P0-1 e P0-2).
echo ""
echo "--- Validação de segurança ---"

ler_env() {  # ler_env NOME -> valor da última ocorrência no .env (vazio se ausente)
  grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

verifica_var() {  # verifica_var NOME "orientação"
  local nome="$1" dica="$2" valor
  valor="$(ler_env "$nome")"
  if [ -z "$valor" ]; then
    fail "$nome não definida no .env — $dica"
  fi
  case "$valor" in
    *"***"*|*changeme*|*troque*)
      fail "$nome ainda está com o PLACEHOLDER do template ('$valor') — $dica" ;;
  esac
  ok "$nome definida"
}

verifica_var POSTGRES_PASSWORD "defina a senha real do banco"
verifica_var DATABASE_URL "ajuste usuário/senha/banco na URL de conexão"
verifica_var ADMIN_PASSWORD "defina a senha do admin inicial (mín. 8 caracteres, sem 'admin123')"
verifica_var COOKIE_KEY "gere com: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\""

# Consistência: o container do banco é criado com POSTGRES_PASSWORD e o app
# conecta com a senha embutida em DATABASE_URL. Se as duas discordarem, o setup
# “passa” e o app morre ao conectar ("password authentication failed") — era
# exatamente o caso do .env.cliente antigo, que trazia senhas diferentes nas
# duas variáveis.
senha_url="$(ler_env DATABASE_URL | sed -n 's|^[a-zA-Z]*://[^:]*:\([^@]*\)@.*|\1|p')"
senha_db="$(ler_env POSTGRES_PASSWORD)"
if [ -z "$senha_url" ]; then
  warn "Não consegui extrair a senha de DATABASE_URL — confira o formato postgresql://usuario:senha@host:porta/banco"
elif [ "$senha_url" != "$senha_db" ]; then
  fail "DATABASE_URL e POSTGRES_PASSWORD discordam sobre a senha do banco (o app não conseguiria conectar)"
else
  ok "DATABASE_URL coerente com POSTGRES_PASSWORD"
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
# Sem `2>/dev/null`: se ADMIN_PASSWORD estiver ausente/fraca, init_admin.py falha
# de propósito e a mensagem precisa aparecer (o banco não nasce com admin padrão).
if docker exec legal-app python init_admin.py; then
  ok "Admin inicial verificado"
else
  fail "Não foi possível criar o admin inicial — veja a mensagem acima e ajuste o .env"
fi

echo ""
echo "========================================================"
echo "  🎉 Setup concluído!"
echo "  👉 Acesse: http://localhost:8501"
echo "  👤 Login: use o ADMIN_EMAIL/ADMIN_PASSWORD do seu .env"
echo "========================================================"