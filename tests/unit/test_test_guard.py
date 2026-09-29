"""The guard that stops the tests from resetting the development database."""

import pytest

from app.core.config import Settings
from tests.support import ensure_test_database_is_separate

DEV = "postgresql+psycopg://navbat:navbat@localhost:5432/navbat"


def _settings(test_url: str, dev_url: str = DEV) -> Settings:
    return Settings(database_url=dev_url, test_database_url=test_url)


def test_refuses_when_both_urls_are_identical():
    with pytest.raises(RuntimeError, match="same database"):
        ensure_test_database_is_separate(_settings(DEV))


def test_refuses_when_urls_differ_only_in_spelling():
    # Different credentials and an explicit default port, same host and database.
    same_db = "postgresql+psycopg://other:secret@localhost/navbat"
    with pytest.raises(RuntimeError, match="same database"):
        ensure_test_database_is_separate(_settings(same_db))


def test_allows_a_different_database_name():
    ensure_test_database_is_separate(
        _settings("postgresql+psycopg://navbat:navbat@localhost:5432/navbat_test")
    )


def test_allows_the_same_database_name_on_a_different_host():
    ensure_test_database_is_separate(
        _settings("postgresql+psycopg://navbat:navbat@ci-postgres:5432/navbat")
    )
