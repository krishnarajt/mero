import logging
import logging.handlers
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

load_dotenv()


def setup_logging():
    """Configure application-wide logging"""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.handlers.TimedRotatingFileHandler(
                "logs/app.log",
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
            ),
        ],
    )

    for noisy in ("asyncio", "sqlalchemy.engine", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured at {log_level} level")
    return logger


logger = setup_logging()

# Imported after logging is configured, so anything they log at import (a
# missing SECRET_KEY, say) goes through the handlers above.
from app.api.auth_routes import router as auth_router  # noqa: E402
from app.api.board_routes import router as board_router  # noqa: E402
from app.api.workspace_routes import router as workspace_router  # noqa: E402
from app.api.ws_routes import router as ws_router  # noqa: E402
from app.db.database import init_db  # noqa: E402
from app.services.persist_service import persister  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("Starting mero Backend...")
    logger.info("=" * 60)

    try:
        await init_db()
        logger.info("✓ Database initialized successfully")
    except Exception as e:
        logger.critical(f"✗ Failed to initialize database: {e}", exc_info=True)
        raise

    # Boards live in this process's memory, so there must be exactly one
    # worker and one replica. The persister writes their strokes behind.
    persister.start()
    logger.info("✓ Stroke persister started")

    logger.info("=" * 60)
    logger.info("mero Backend is ready!")
    logger.info("=" * 60)

    yield

    logger.info("Shutting down mero Backend...")
    # Flush every queued stroke before the process goes.
    await persister.stop()


app = FastAPI(
    title="mero Backend",
    description="Realtime infinite whiteboards",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    # Auth is a bearer header, never a cookie.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(f"CORS enabled for origins: {cors_origins}")

for router in (auth_router, workspace_router, board_router):
    app.include_router(router, prefix="/api")
app.include_router(ws_router)
logger.info("API routers registered")


@app.get("/")
def root():
    return {
        "name": "mero Backend",
        "description": "Realtime infinite whiteboards",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
def health_check():
    """Health check endpoint for k8s"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ready")
def readiness_check():
    """Readiness check endpoint for k8s"""
    return {"status": "ready", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "1184"))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    logger.info(f"Starting server on port {port}, reload={reload}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload, log_level="info")
