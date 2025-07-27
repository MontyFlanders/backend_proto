# Default ENV_FILE if not set by caller
ENV_FILE ?= .env.local

up:
	docker compose --env-file .env.local up --build

up-staging:
	$(MAKE) up ENV_FILE=.env.staging

up-prod:
	$(MAKE) up ENV_FILE=.env.production

down:
	docker compose --env-file $(ENV_FILE) down

logs:
	docker compose --env-file $(ENV_FILE) logs -f

test:
	ENV_FILE=$(ENV_FILE) pytest app/tests
