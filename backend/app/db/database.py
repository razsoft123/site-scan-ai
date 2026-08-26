import os
from dotenv import load_dotenv, find_dotenv

from sqlalchemy import create_engine, URL
from sqlalchemy.orm import sessionmaker

env_path = find_dotenv()
if env_path:
    load_dotenv(env_path)

db_url = URL.create(
    "postgresql+psycopg2",
    username= os.getenv("DB_USERNAME"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT") or "5432"),
    database=os.getenv("DB_NAME")
)

engine = create_engine(db_url, pool_pre_ping=True)
session = sessionmaker(bind=engine, autoflush=True, autocommit=False)

def get_db():
    db = session()
    try:
        yield db
    finally:
        db.close()
