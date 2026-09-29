"""Database engine and per-request session.

Synchronous SQLAlchemy on purpose (see ADR 0003): simpler to reason about and
to test at this scale. P1.1 extends this module with the commit/rollback policy
for requests; P0.3 only needs a session to prove the database is reachable.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# pool_pre_ping drops connections the server closed (e.g. after a DB restart)
# instead of failing the next request with a stale-connection error.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    with SessionLocal() as db:
        yield db
