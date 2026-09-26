"""Provision the data analyst's limited login for deploy and flag history."""

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.settings import settings

ROLE = "history_ro"


def history_url_for_database(database_url: str) -> str:
    """Use the configured history credential against the database being migrated or tested."""
    configured = make_url(settings.history_db_url)
    if (
        configured.username != ROLE
        or not configured.password
        or configured.password == "REPLACE_WITH_RANDOM_PASSWORD"
    ):
        raise ValueError("HISTORY_DB_URL must contain the history_ro login and a random password")
    return (
        make_url(database_url)
        .set(username=ROLE, password=configured.password)
        .render_as_string(hide_password=False)
    )


async def setup_history_reader() -> None:
    """Grant SELECT on only the two history tables in the current database."""
    password = make_url(history_url_for_database(settings.database_url)).password
    database = make_url(settings.database_url).database
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        exists = await conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        if await exists.fetchone() is None:
            await conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
                    sql.Identifier(ROLE), sql.Literal(password)
                )
            )
        else:
            await conn.execute(
                sql.SQL("ALTER ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
                    sql.Identifier(ROLE), sql.Literal(password)
                )
            )
        await conn.execute(
            sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(
                sql.Identifier(ROLE)
            )
        )
        await conn.execute(
            sql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(sql.Identifier(ROLE))
        )
        await conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(ROLE)
            )
        )
        await conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(ROLE))
        )
        await conn.execute(
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
                sql.Identifier(ROLE)
            )
        )
        await conn.execute(
            sql.SQL("GRANT SELECT ON deploys, flag_changes TO {}").format(sql.Identifier(ROLE))
        )
