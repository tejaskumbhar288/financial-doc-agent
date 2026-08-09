"""Database connection and session management."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Connection string for local development (via docker-compose)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://financial_user:financial_pass@localhost:5432/financial_doc_agent",
)

# SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True to see SQL queries logged
    future=True,
)

# Session factory
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)


def get_db() -> Session:
    """
    Dependency function for FastAPI routes.
    Usage: @app.get("/") def my_route(db: Session = Depends(get_db)): ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
