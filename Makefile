# ----- config -----
SHELL := /bin/bash
ENV_FILE ?= .env

# Compose needs two things:
#  - ENV_FILE in its *environment* (because your docker-compose.yml uses ${ENV_FILE} in env_file:)
#  - an --env-file to load vars for interpolation (we reuse the same file)
COMPOSE_CMD = ENV_FILE=$(ENV_FILE) docker compose --env-file $(ENV_FILE)

.PHONY: up up-d up-staging up-prod down logs ps wait-postgres test test-quick

# ----- compose -----
up:        ## Build and start in foreground
	@[[ -f "$(ENV_FILE)" ]] || { echo "Missing $(ENV_FILE)"; exit 1; }
	$(COMPOSE_CMD) up --build

up-d:      ## Build and start detached
	@[[ -f "$(ENV_FILE)" ]] || { echo "Missing $(ENV_FILE)"; exit 1; }
	$(COMPOSE_CMD) up -d --build

up-staging:
	$(MAKE) up-d ENV_FILE=.env.staging

up-prod:
	$(MAKE) up-d ENV_FILE=.env.production

down:      ## Stop stack
	$(COMPOSE_CMD) down

logs:      ## Tail logs
	$(COMPOSE_CMD) logs -f

ps:        ## Show services
	$(COMPOSE_CMD) ps

wait-postgres: ## Wait for DB to be ready
	@echo "Waiting for Postgres..."
	$(COMPOSE_CMD) exec -T postgis bash -lc 'for i in $$(seq 1 30); do pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB && exit 0; sleep 1; done; exit 1'

# ----- tests -----
test: up-d wait-postgres  ## Bring up deps, then run tests
	@set -a; [[ -f "$(ENV_FILE)" ]] && source "$(ENV_FILE)"; set +a; \
	DB_HOST=127.0.0.1 pytest -q tests

test-quick:               ## Run tests assuming stack already up
	@set -a; [[ -f "$(ENV_FILE)" ]] && source "$(ENV_FILE)"; set +a; \
	DB_HOST=127.0.0.1 pytest -q tests
