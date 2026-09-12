"""One authoritative PostgreSQL transaction per request; no SQLite fallback."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@lru_cache
def get_engine():
    from app.config import get_settings

    url = str(get_settings().database_url)
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Personal Staffer requires PostgreSQL with psycopg")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True)


def session_factory():
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_session():
    with session_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
