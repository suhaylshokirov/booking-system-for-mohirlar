"""Health check: can the app reach its database?"""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError


def check_database(db: Session) -> None:
    """Run `SELECT 1`.

    Raises AppError 503 `DATABASE_UNAVAILABLE` if the database can't answer, so
    load balancers and Docker healthchecks see the app as unhealthy.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise AppError(
            "DATABASE_UNAVAILABLE", "The database is not reachable.", status_code=503
        ) from exc
