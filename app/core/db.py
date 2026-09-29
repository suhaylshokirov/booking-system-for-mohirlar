"""Database engine and per-request session.

Synchronous SQLAlchemy on purpose (see ADR 0003): simpler to reason about and
to test at this scale.

Transaction policy: one request = one session = one transaction. The request
commits if the handler returns normally and rolls back if it raises, so a
booking and its `booking_events` row are written together or not at all.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# pool_pre_ping drops connections the server closed (e.g. after a DB restart)
# instead of failing the next request with a stale-connection error.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
# expire_on_commit=False: objects stay readable after the commit at the end of
# the request, when FastAPI serialises the response.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed or rolled back.

    Commits after the handler returns. If the handler raised, the exception
    arrives at the `yield` and skips the commit; leaving the `with` block then
    closes the session, which rolls back anything uncommitted. Services
    therefore never call `commit()` themselves. Use it through `DbSession`, not
    `Depends(get_db)`, so the commit happens before the response is sent.
    """
    with SessionLocal() as db:
        yield db
        db.commit()


# scope="function" runs the code after `yield` (the commit) as soon as the
# handler returns, *before* the response is sent. With the default scope it
# runs after the response, so a failed commit would leave the client holding a
# success response for data that was never saved.
DbSession = Annotated[Session, Depends(get_db, scope="function")]
