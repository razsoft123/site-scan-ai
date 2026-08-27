import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.models  # Register all tables with SQLAlchemy metadata.
from app.core.register_handlers import register_exception_handlers
from app.db.base import Base
from app.db.database import engine
from app.routes.audit import router as audit_router
from app.routes.auth import router as auth_router

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            Base.metadata.create_all(bind=connection)
    except SQLAlchemyError:
        logger.exception("Database initialization failed")
        raise

    try:
        yield
    finally:
        engine.dispose()
        logger.info("Database connection pool closed")


app = FastAPI(title="Site Scan AI API", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(audit_router)


@app.get("/health")
def get_health() -> dict[str, str]:
    return {
        "status": "Server is running",
        "time": "time",
    }
