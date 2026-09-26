TEST_DATABASE_URL = postgresql://triage:triage@localhost:5433/triage_test

.PHONY: install db migrate migration check-migrations api worker send deploy flag test test-db lint fmt \
	sandbox sandbox-images shop-up shop-down test-sandbox test-shop test-llm test-spike analyst-images models

install:            ## install Python deps (uv) and pin them in uv.lock
	uv sync

db:                 ## start the agent Postgres (pgvector) on localhost:5433
	docker compose up -d db

migrate:            ## Alembic migrations + Procrastinate queue + LangGraph checkpoint tables + seed
	uv run python -m app.migrate

migration:          ## after changing app/tables.py: make migration m="add foo to tickets"
	uv run alembic revision --autogenerate -m "$(m)"

check-migrations:   ## fails if app/tables.py has changes that no migration covers
	uv run alembic check

api:                ## FastAPI on :8000
	uv run uvicorn app.api.main:app --reload --port 8000

worker:             ## Procrastinate worker that runs the LangGraph pipeline
	uv run python -m procrastinate --app=app.tasks.app worker

send:               ## send a demo ticket: make send t=4
	uv run python scenarios/send_ticket.py $(t)

sandbox:            ## clone the shop at the pinned commit, apply the planted bugs, tag v1.3.0 and v1.4.0
	./sandbox/setup.sh

sandbox-images:     ## build sandbox/<service>:<tag> for the four versioned services at both tags
	./sandbox/build-images.sh

shop-up:            ## start the shop (minimal mode), versioned services at the tags in versions.env
	./sandbox/compose.sh up --detach --force-recreate --remove-orphans --no-build

shop-down:          ## stop the shop and delete its volumes
	./sandbox/compose.sh down --remove-orphans --volumes

scenario-%:         ## set up a demo ticket's condition, place its orders, send it: make scenario-4
	uv run python scenarios/scenario.py $*

deploy:             ## deploy a sandbox service version: make deploy s=payment v=v1.4.0
	./scenarios/deploy.sh $(s) $(v)

flag:               ## change a flagd flag: make flag f=paymentFailure v=25%
	./scenarios/flag.sh $(f) $(v)

test:               ## unit tests and the graph end to end, no database needed
	uv run pytest -q

test-db:            ## tests against Postgres, on a throwaway triage_test database (needs make db)
	docker compose exec -T db sh -c 'dropdb -U triage --if-exists --force triage_test && createdb -U triage triage_test'
	DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -q -m db

test-sandbox:       ## the shop fork: tags, planted bugs, overlay, images (needs make sandbox)
	uv run pytest -q -m sandbox

test-shop:          ## every scenario against the running shop (needs make shop-up; a few minutes)
	docker compose exec -T db sh -c 'dropdb -U triage --if-exists --force triage_test && createdb -U triage triage_test'
	DATABASE_URL=$(TEST_DATABASE_URL) uv run python -m app.migrate
	DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -q -m shop

test-llm:           ## real model calls on each provider profile (needs keys in .env.agent)
	uv run pytest -q -m llm

models:             ## which model each role uses (ROLE_PROFILE, ROLE_MODELS) and missing keys
	uv run python -m app.models_config

analyst-images:     ## the analysts' containers: HolmesGPT (holmes/) and the read-only codebox
	docker build -t sandbox/holmes:0.42.0 holmes/
	docker build -t sandbox/codebox codebox/

test-spike:         ## HolmesGPT and mini-swe-agent investigate demo tickets (needs shop-up, analyst-images)
	docker compose exec -T db sh -c 'dropdb -U triage --if-exists --force triage_test && createdb -U triage triage_test'
	DATABASE_URL=$(TEST_DATABASE_URL) uv run python -m app.migrate
	DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -q -m spike

lint:
	uv run ruff check .

fmt:
	uv run ruff format . && uv run ruff check --fix .
