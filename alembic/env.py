"""
Alembic environment configuration.

Loads DATABASE_URL the same way the application does and exposes the app's
SQLAlchemy metadata for autogenerate support. The app's engine is async, so
the CLI runs migrations through an async engine, and the app (already inside
an event loop at startup) hands in a connection of its own instead.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The CLI doesn't go through main.py, so pick up .env here too.
load_dotenv(PROJECT_ROOT / ".env")

from app.db.database import Base, DATABASE_URL  # noqa: E402

# Import the models module so Base.metadata is fully populated for autogenerate.
import app.db.models  # noqa: E402, F401

config = context.config
# configparser treats % as interpolation; a password may contain one.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

# alembic.ini's [logger_root] is WARN, which is right for `alembic upgrade` on
# a terminal and wrong inside the app: the app runs migrations itself at
# startup, and reconfiguring logging there would silence every INFO line after
# it. run_migrations() in app/db/database.py sets this attribute to say "the
# host process owns logging"; the CLI leaves it unset.
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite can't ALTER most things; batch mode rebuilds the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
