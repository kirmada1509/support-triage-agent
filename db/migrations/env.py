"""Alembic environment: async engine on the psycopg 3 driver, URL from app.settings.

Procrastinate's and LangGraph's tables share this database. They aren't in our metadata, so
include_object hides them from autogenerate; otherwise it would try to drop them.
"""

import asyncio
import logging
import warnings

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.settings import settings
from app.tables import Base

config = context.config
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)-5.5s [%(name)s] %(message)s")
    logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = Base.metadata

# Postgres rewrites generated-column expressions (adds ::regconfig casts and so on), so Alembic's
# text comparison always differs for retrieval_docs.tsv. Harmless; hide the noise.
warnings.filterwarnings("ignore", message="Computed default on retrieval_docs.tsv")


def database_url() -> str:
    """Tests pass their own URL through the Alembic config; everything else uses settings."""
    return config.attributes.get("url") or settings.sqlalchemy_url


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "table" and reflected and compare_to is None)


def configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_object=include_object,
        compare_server_default=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    configure(url=database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
