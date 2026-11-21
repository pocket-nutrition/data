import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pocket_nutrition:pocket_nutrition@postgresql:5432/pocket_nutrition")


def _psycopg2_url(url: str):
    """Pin bare postgresql:// URLs to psycopg2 (SQLAlchemy 2.1 defaults to psycopg 3)."""
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        return parsed.set(drivername="postgresql+psycopg2")
    return parsed


engine = create_engine(_psycopg2_url(DATABASE_URL), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()
