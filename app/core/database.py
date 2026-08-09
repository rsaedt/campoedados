from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """Normaliza URLs comuns para o driver psycopg 3 usado na homologação."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _is_transaction_pooler(url: str) -> bool:
    try:
        return urlparse(url.replace("postgresql+psycopg://", "postgresql://")).port == 6543
    except ValueError:
        return False


def build_engine(url: str = "sqlite:///./campoedados.db"):
    normalized = normalize_database_url(url)
    if normalized.startswith("sqlite"):
        return create_engine(
            normalized,
            future=True,
            connect_args={"check_same_thread": False},
        )

    common = {
        "future": True,
        "pool_pre_ping": True,
    }
    # Supavisor transaction mode (6543) não deve manter pool local persistente.
    if _is_transaction_pooler(normalized) or os.getenv("CAMPOEDADOS_DB_NULL_POOL", "").lower() in {"1", "true", "yes"}:
        return create_engine(normalized, poolclass=NullPool, **common)

    return create_engine(
        normalized,
        pool_size=int(os.getenv("CAMPOEDADOS_DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("CAMPOEDADOS_DB_MAX_OVERFLOW", "2")),
        pool_timeout=int(os.getenv("CAMPOEDADOS_DB_POOL_TIMEOUT", "15")),
        pool_recycle=int(os.getenv("CAMPOEDADOS_DB_POOL_RECYCLE", "1800")),
        **common,
    )


def build_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def database_is_ready(db_engine=None) -> bool:
    target = db_engine or engine
    try:
        with target.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./campoedados.db")
engine = build_engine(DATABASE_URL)
SessionLocal = build_session_factory(engine)


def get_db():
    with SessionLocal() as session:
        yield session
