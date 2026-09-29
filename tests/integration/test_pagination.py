"""The paging convention itself (P3.4): `get_page_params` and `paginate`.

`test_services.py` and `test_providers.py` prove each endpoint pages; this file
proves the helper they share, with one endpoint per rule as a smoke test.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, PageParams, get_page_params, paginate
from app.models import Provider, Service


def _services(db: Session, count: int) -> None:
    for n in range(count):
        db.add(Service(name=f"Service {n:02}", duration_minutes=30, price=1000))
    db.flush()


def _by_name():
    return select(Service).order_by(Service.name, Service.id)


def test_defaults_are_20_items_from_the_start():
    assert get_page_params() == PageParams(limit=20, offset=0)
    assert (DEFAULT_LIMIT, MAX_LIMIT) == (20, 100)


def test_pages_cover_every_row_exactly_once_and_total_is_the_same_on_each(db):
    _services(db, 7)

    pages = [paginate(db, _by_name(), PageParams(limit=3, offset=o)) for o in (0, 3, 6)]

    assert [len(items) for items, _ in pages] == [3, 3, 1]
    assert [total for _, total in pages] == [7, 7, 7]
    names = [s.name for items, _ in pages for s in items]
    assert names == [f"Service {n:02}" for n in range(7)]  # in order, no repeats, no gaps


def test_total_counts_matching_rows_not_the_page_and_respects_filters(db):
    _services(db, 5)
    db.add(Service(name="Hidden", duration_minutes=30, price=1, is_active=False))
    db.flush()

    items, total = paginate(db, _by_name().where(Service.is_active), PageParams(limit=2, offset=0))

    assert len(items) == 2
    assert total == 5  # the inactive one is not counted


def test_an_offset_past_the_end_is_an_empty_page_with_the_real_total(db):
    _services(db, 3)
    assert paginate(db, _by_name(), PageParams(limit=20, offset=50)) == ([], 3)


def test_an_empty_table_is_no_items_and_zero(db):
    assert paginate(db, _by_name(), PageParams(limit=20, offset=0)) == ([], 0)


def test_a_limit_larger_than_the_data_returns_everything(db):
    _services(db, 4)
    items, total = paginate(db, _by_name(), PageParams(limit=100, offset=0))
    assert (len(items), total) == (4, 4)


# --- through the API -------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/services", "/api/v1/providers"])
def test_every_list_uses_the_same_envelope_and_defaults(client, path):
    body = client.get(path).json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


@pytest.mark.parametrize("path", ["/api/v1/services", "/api/v1/providers"])
@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"limit": "many"}, {"offset": -1}, {"offset": "x"}],
)
def test_bad_paging_parameters_are_a_422_naming_the_parameter(client, path, params):
    response = client.get(path, params=params)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["errors"][0]["field"] == f"query.{next(iter(params))}"


def test_the_maximum_page_size_is_accepted_and_echoed(client, db):
    db.add(Provider(name="Jasur"))
    db.flush()
    body = client.get("/api/v1/providers", params={"limit": 100}).json()
    assert (body["limit"], body["total"], len(body["items"])) == (100, 1, 1)
