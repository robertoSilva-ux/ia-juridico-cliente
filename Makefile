.PHONY: up down restart logs test test-local lint lint-fix clean setup dev db-dev db-dev-stop

up:
	docker compose up -d --build

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

# --- Desenvolvimento nativo (sem Docker) — ver docs/AMBIENTE_DEV.md ---
# Banco em podman rootless + Ollama no host + app em venv local.
db-dev:
	bash scripts/db-dev.sh start

db-dev-stop:
	bash scripts/db-dev.sh stop

dev:
	bash scripts/dev.sh

# Testes no container (ambiente real: mesmas dependências da imagem).
# O runner roda cada módulo em processo separado — ver app/run_tests.sh.
test:
	docker exec -w /app legal-app bash run_tests.sh

# Testes no host (exige um venv com app/requirements.txt instalado).
test-local:
	bash app/run_tests.sh

# Lint (ruff) roda dentro do container, onde o ruff está instalado.
# O código fonte é copiado para /app no build; reflete o estado commitado.
lint:
	docker exec -w /app legal-app ruff check .

lint-fix:
	docker exec -w /app legal-app ruff check . --fix

shell:
	docker exec -it legal-app bash

clean:
	docker compose down -v
	docker system prune -f

setup: up
	@echo "Aguardando serviços..."
	@sleep 10
	docker exec legal-app python init_admin.py
