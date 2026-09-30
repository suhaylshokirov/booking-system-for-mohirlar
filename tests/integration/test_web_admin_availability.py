"""Availability editor (P9.4): access, rules, exceptions, overlap errors, conflict notice.

Frozen clock: Thursday 2026-10-01 07:00 UTC, 12:00 in Tashkent.
"""

from datetime import UTC, date, datetime, time

import pytest

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import AvailabilityException, AvailabilityRule, Provider, ProviderService, Service
from app.models.user import User, UserRole
from app.services.booking import create_booking
from tests.integration.test_web_admin_dashboard import NOW

CSRF = "test-csrf-token"


def _user(db, email, role) -> User:
    user = User(email=email, password_hash="x", full_name="T P", role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def staff(db) -> User:
    return _user(db, "staff@example.com", UserRole.ADMIN)


@pytest.fixture
def jasur(db) -> Provider:
    provider = Provider(name="Jasur")
    db.add(provider)
    db.flush()
    return provider


def _sign_in(client, user) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, NOW))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _post(client, path, **data):
    return client.post(path, data={"csrf_token": CSRF, **data}, follow_redirects=False)


def _rules(db, provider):
    return db.query(AvailabilityRule).filter_by(provider_id=provider.id).all()


def _url(provider, tail=""):
    return f"/admin/providers/{provider.id}/availability{tail}"


def test_a_customer_gets_404_and_a_visitor_a_login_redirect(client, db, jasur):
    assert client.get(_url(jasur), follow_redirects=False).status_code == 303
    _sign_in(client, _user(db, "c@example.com", UserRole.CUSTOMER))

    assert client.get(_url(jasur)).status_code == 404
    assert _post(client, _url(jasur, "/rules"), weekday="0").status_code == 404


def test_an_unknown_provider_is_404(client, staff):
    _sign_in(client, staff)

    assert client.get("/admin/providers/999999/availability").status_code == 404


def test_add_a_weekly_window_and_see_it_grouped_by_day(client, db, staff, jasur):
    _sign_in(client, staff)

    response = _post(
        client, _url(jasur, "/rules"), weekday="4", start_time="09:00", end_time="12:00"
    )

    assert response.status_code == 303
    (rule,) = _rules(db, jasur)
    assert (rule.weekday, rule.start_time, rule.end_time) == (4, time(9), time(12))
    html = client.get(_url(jasur)).text
    assert "09:00–12:00" in html
    assert "Not working" in html  # the other six days


def test_an_overlapping_window_is_refused_with_the_services_message(client, db, staff, jasur):
    db.add(AvailabilityRule(provider_id=jasur.id, weekday=4, start_time=time(9), end_time=time(12)))
    db.flush()
    _sign_in(client, staff)

    response = _post(
        client, _url(jasur, "/rules"), weekday="4", start_time="11:00", end_time="13:00"
    )

    assert response.status_code == 409
    assert "overlaps another working window" in response.text
    assert 'value="13:00"' in response.text  # what was typed is kept
    assert len(_rules(db, jasur)) == 1


def test_touching_windows_are_fine(client, db, staff, jasur):
    db.add(AvailabilityRule(provider_id=jasur.id, weekday=4, start_time=time(9), end_time=time(12)))
    db.flush()
    _sign_in(client, staff)

    response = _post(
        client, _url(jasur, "/rules"), weekday="4", start_time="12:00", end_time="14:00"
    )

    assert response.status_code == 303


@pytest.mark.parametrize(
    ("start", "end", "text"),
    [
        ("09:10", "12:00", "multiple of 15 minutes"),  # off the slot grid
        ("12:00", "09:00", "Check the form"),  # ends before it starts
        ("", "12:00", "Check the form"),
    ],
)
def test_a_bad_window_is_refused(client, db, staff, jasur, start, end, text):
    _sign_in(client, staff)

    response = _post(client, _url(jasur, "/rules"), weekday="1", start_time=start, end_time=end)

    assert response.status_code == 422
    assert text in response.text
    assert _rules(db, jasur) == []


def test_remove_a_window(client, db, staff, jasur):
    rule = AvailabilityRule(provider_id=jasur.id, weekday=1, start_time=time(9), end_time=time(12))
    db.add(rule)
    db.flush()
    _sign_in(client, staff)

    response = _post(client, _url(jasur, f"/rules/{rule.id}/delete"))

    assert response.status_code == 303
    assert _rules(db, jasur) == []


def test_a_day_off_and_custom_hours(client, db, staff, jasur):
    _sign_in(client, staff)

    _post(client, _url(jasur, "/exceptions"), date="2026-10-12", reason="Holiday")
    _post(
        client, _url(jasur, "/exceptions"), date="2026-10-13", start_time="12:00", end_time="16:00"
    )

    off, custom = db.query(AvailabilityException).order_by(AvailabilityException.date)
    assert (off.date, off.start_time, off.reason) == (date(2026, 10, 12), None, "Holiday")
    assert (custom.start_time, custom.end_time) == (time(12), time(16))
    html = client.get(_url(jasur)).text
    assert "Day off" in html and "12:00–16:00" in html


def test_an_exception_in_the_past_or_twice_on_one_date_is_refused(client, db, staff, jasur):
    _sign_in(client, staff)

    past = _post(client, _url(jasur, "/exceptions"), date="2026-09-30")
    _post(client, _url(jasur, "/exceptions"), date="2026-10-12")
    twice = _post(client, _url(jasur, "/exceptions"), date="2026-10-12")

    assert past.status_code == 422 and "before today" in past.text
    assert twice.status_code == 409
    assert db.query(AvailabilityException).count() == 1


def test_remove_an_exception(client, db, staff, jasur):
    row = AvailabilityException(provider_id=jasur.id, date=date(2026, 10, 12))
    db.add(row)
    db.flush()
    _sign_in(client, staff)

    _post(client, _url(jasur, f"/exceptions/{row.id}/delete"))

    assert db.query(AvailabilityException).count() == 0


def test_the_editor_lists_bookings_that_no_longer_fit(client, db, staff, jasur):
    haircut = Service(name="Haircut", duration_minutes=30, price=60_000)
    db.add(haircut)
    db.flush()
    db.add(ProviderService(provider_id=jasur.id, service_id=haircut.id))
    rule = AvailabilityRule(provider_id=jasur.id, weekday=4, start_time=time(9), end_time=time(12))
    db.add(rule)
    db.flush()
    customer = _user(db, "aziza@example.com", UserRole.CUSTOMER)
    create_booking(
        db, customer, haircut.id, jasur.id, datetime(2026, 10, 2, 4, tzinfo=UTC), None, NOW
    )
    _sign_in(client, staff)
    assert "no longer fit" not in client.get(_url(jasur)).text

    # Close that Friday: the 09:00 booking is now outside the hours.
    _post(client, _url(jasur, "/exceptions"), date="2026-10-02")

    html = client.get(_url(jasur)).text
    assert "1 upcoming booking no longer fits" in html
    assert "that date is closed" in html
