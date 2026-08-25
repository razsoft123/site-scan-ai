from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import engine
from app.db.base import Base

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifesapn(_: FastAPI):
    try:
        with engine.begin() as connection :
            connection.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            Base.metadata.create_all(bind=connection)
    except SQLAlchemyError:
        logger.error("Database initialization failed")
        raise

    finally :
        yield
        engine.dispose()
        logger.info("Database connetion pool closed")


app = FastAPI(title="Site Scan AI API", lifespan=lifesapn)

@app.get("/health")
def get_health():
    return {
        "status": "Server is running",
        "time": "time"
    }