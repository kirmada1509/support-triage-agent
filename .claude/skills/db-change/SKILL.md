---
name: db-change
description: Change the agent's Postgres schema (tables, columns, indexes, triggers) with SQLAlchemy models and Alembic. Use when adding or changing anything in app/tables.py or db/migrations/.
---

# Change the database

Our tables are SQLAlchemy 2.0 models in `app/tables.py`; every query lives in `app/db.py`.
Procrastinate and the LangGraph checkpointer own their own tables: never touch those.

1. **Test first** in `tests/test_db.py` (marker `db`): the query or constraint you need,
   against the real database. Add new tables to its `TABLES` truncate list.
2. **Edit `app/tables.py`**, then write the query in `app/db.py` (async sessions).
3. **Generate the migration:** `make migration m="add priority to tickets"`. Read the file in
   `db/migrations/versions/`: autogenerate misses triggers, functions, extensions and data
   changes; write those by hand, with a working `downgrade()` (0001's NOTIFY trigger is the
   example).
4. **Apply and check:** `make migrate`, then `make check-migrations` (fails if a model change
   has no migration), then `make test-db`. The db suite migrates down to nothing and back up, so
   a broken downgrade fails it.
5. **Never edit an applied migration**; add a new one.
6. If `make migrate` says a table already exists but Alembic has no record of it, the dev
   database predates the migrations: ask the user before recreating it
   (`docker compose down -v && make db && make migrate` deletes the dev data).
7. Finish with the `wrap-up` skill.
