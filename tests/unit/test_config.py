"""Settings: the database URL is normalised to the psycopg 3 driver."""

import pytest

from app.core.config import Settings

PSYCOPG3 = "postgresql+psycopg://u:p@host/db?sslmode=require"


@pytest.mark.parametrize(
    "given",
    [
        "postgres://u:p@host/db?sslmode=require",
        "postgresql://u:p@host/db?sslmode=require",
        PSYCOPG3,
    ],
)
def test_database_url_always_names_the_psycopg3_driver(given: str) -> None:
    """Neon gives `postgres://`; SQLAlchemy would then look for psycopg2."""
    assert Settings(database_url=given).database_url == PSYCOPG3


def test_test_database_url_is_normalised_too() -> None:
    settings = Settings(test_database_url="postgres://u:p@host/db")
    assert settings.test_database_url == "postgresql+psycopg://u:p@host/db"
