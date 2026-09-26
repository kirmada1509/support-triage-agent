.PHONY: install db migrate migration check-migrations api worker send deploy flag test test-db lint fmt \
	sandbox sandbox-images shop-up shop-down

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
	DATABASE_URL=postgresql://triage:triage@localhost:5433/triage_test uv run pytest -q -m db

lint:
	uv run ruff check .

fmt:
	uv run ruff format . && uv run ruff check --fix .
