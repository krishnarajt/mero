import logging
import os
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return "sqlite+aiosqlite:///./mero.db"
    # Accept the plain URLs the other apps use and pick the async driver here,
    # so the Vault value can look the same as everywhere else.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    for sync_prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql://"):
        if url.startswith(sync_prefix):
            return "postgresql+asyncpg://" + url[len(sync_prefix):]
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    return url


DATABASE_URL = _database_url()


def _make_engine() -> AsyncEngine:
    if DATABASE_URL.startswith("sqlite"):
        return create_async_engine(DATABASE_URL)
    return create_async_engine(DATABASE_URL, pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=300)


engine = _make_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    """Dependency for getting database session"""
    async with SessionLocal() as db:
        yield db


# The revision that matches the schema create_all() built before migrations
# existed. A database from then has the tables but no alembic_version.
BASELINE_REVISION = "0001"


async def run_migrations() -> None:
    """Run Alembic migrations to the latest revision."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    # script_location in alembic.ini is relative to the working directory; pin
    # it so the app can be started from anywhere.
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    # The app owns logging; see the note in alembic/env.py.
    alembic_cfg.attributes["configure_logging"] = False

    def upgrade(sync_conn):
        # We are already inside the event loop, so env.py can't start its own
        # async engine. It uses this connection instead.
        alembic_cfg.attributes["connection"] = sync_conn
        insp = inspect(sync_conn)
        if insp.has_table("users") and not insp.has_table("alembic_version"):
            logger.info("Existing schema without a revision: stamping %s", BASELINE_REVISION)
            command.stamp(alembic_cfg, BASELINE_REVISION)
        command.upgrade(alembic_cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(upgrade)


async def init_db(use_alembic: bool | None = None) -> None:
    """Initialize database tables.

    Alembic by default: the app runs `alembic upgrade head` on startup, so a
    deploy that adds a migration applies it without a separate step. Set
    USE_ALEMBIC_MIGRATIONS=false to fall back to create_all(), which builds the
    current schema but records no revision.
    """
    import app.db.models  # noqa: F401  (registers every model on Base)

    if DATABASE_URL.startswith("sqlite"):
        # Readers don't block the write-behind persister.
        async with engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")

    if use_alembic is None:
        use_alembic = os.getenv("USE_ALEMBIC_MIGRATIONS", "true").lower() == "true"

    if use_alembic:
        await run_migrations()
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
