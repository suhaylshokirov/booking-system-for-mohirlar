"""The test harness itself: isolation, real commits, clock, migrated schema.

The probe table stands in for real models (which arrive in P1). The pairs of
tests below depend on running in file order: the first leaves data behind (or
tries to), the second proves it is gone.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text


@pytest.fixture(scope="module", autouse=True)
def probe_table(engine):
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE harness_probe (note text NOT NULL)"))
    yield
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE harness_probe"))


def _count(session) -> int:
    return session.execute(text("SELECT count(*) FROM harness_probe")).scalar_one()


def test_rollback_isolation_part_1_row_is_visible_inside_its_own_test(db):
    db.execute(text("INSERT INTO harness_probe VALUES ('from test 1')"))
    db.commit()  # even an explicit commit must not outlive the test

    assert _count(db) == 1


def test_rollback_isolation_part_2_row_from_the_previous_test_is_gone(db):
    assert _count(db) == 0


def test_db_work_is_not_visible_to_other_connections(db, engine):
    db.execute(text("INSERT INTO harness_probe VALUES ('uncommitted')"))

    with engine.connect() as other_connection:
        rows = other_connection.execute(text("SELECT count(*) FROM harness_probe")).scalar_one()
    assert rows == 0


def test_committing_db_part_1_rows_are_really_committed(committing_db, engine):
    with committing_db() as session:
        session.execute(text("INSERT INTO harness_probe VALUES ('committed')"))
        session.commit()

    with engine.connect() as other_connection:
        rows = other_connection.execute(text("SELECT count(*) FROM harness_probe")).scalar_one()
    assert rows == 1


def test_committing_db_part_2_tables_were_truncated_afterwards(db):
    assert _count(db) == 0


def test_client_uses_the_rolled_back_session(client, db):
    db.execute(text("INSERT INTO harness_probe VALUES ('seen by the api')"))

    # The health endpoint runs on the same session the test holds, so it would
    # fail if `client` had been given its own connection to a different state.
    assert client.get("/api/v1/health").status_code == 200


def test_client_and_frozen_clock_share_one_instant(client, frozen_clock):
    from app.core.clock import get_clock

    assert client.app.dependency_overrides[get_clock]() is frozen_clock
    assert frozen_clock.now() == datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
