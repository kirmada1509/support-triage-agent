"""`make migrate`: bring the database up to date. Safe to run any number of times.

1. Our tables: Alembic migrations (db/migrations), generated from app/tables.py.
2. Procrastinate's queue tables and LangGraph's checkpoint tables: each library's own setup.
3. The demo tenant.
"""

import asyncio

import psycopg
from alembic import command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app import db
from app.alembic_config import alembic_config
from app.settings import settings
from app.tasks import app as procrastinate_app


async def setup_libraries() -> None:
    url = settings.database_url
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        cur = await conn.execute("SELECT to_regclass('procrastinate_jobs') IS NOT NULL")
        has_queue = (await cur.fetchone())[0]
    if not has_queue:  # Procrastinate's schema script isn't idempotent
        async with procrastinate_app.open_async():
            await procrastinate_app.schema_manager.apply_schema_async()
        print("applied procrastinate schema")

    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
    print("applied langgraph checkpoint tables")


async def seed() -> None:
    await db.upsert_tenant("figma-merch", "Figma Merch Store", "figma-shopper", plan="Enterprise")
    await db.engine.dispose()
    print("seeded tenant figma-merch")


async def setup_rest() -> None:
    await setup_libraries()
    await seed()


def main() -> None:
    command.upgrade(alembic_config(), "head")  # runs its own event loop, so before ours
    asyncio.run(setup_rest())


if __name__ == "__main__":
    main()
