.PHONY: up down restart logs test lint clean setup

up:
	docker compose up -d --build

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

test:
	cd app && python -m pytest test_auth.py test_management.py -v

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
