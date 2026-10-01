"""Business settings page (P9.6): access, save, validation, granularity conflict."""

import pytest

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import Service
from app.models.user import User, UserRole
from app.services.business_settings import get_business_settings
from tests.integration.test_web_barber_dashboard import NOW
from tests.support import add_barber

CSRF = "test-csrf-token"


def _user(db, role) -> User:
    user = User(email=f"{role.value}@example.com", password_hash="x", full_name="T P", role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def staff(db) -> User:
    return add_barber(db, "staff@example.com")


def _sign_in(client, user) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, NOW))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _form(**overrides):
    return {
        "name": "Barbershop Navbat",
        "timezone": "Asia/Samarkand",
        "currency": "uzs",
        "slot_granularity_minutes": "30",
        "min_lead_time_minutes": "0",
        "max_booking_horizon_days": "30",
        "cancellation_cutoff_hours": "4",
    } | overrides


def _save(client, **overrides):
    return client.post(
        "/barber/settings", data={"csrf_token": CSRF, **_form(**overrides)}, follow_redirects=False
    )


def test_a_customer_gets_404_and_a_visitor_a_login_redirect(client, db):
    assert client.get("/barber/settings", follow_redirects=False).status_code == 303
    _sign_in(client, _user(db, UserRole.CUSTOMER))

    assert client.get("/barber/settings").status_code == 404
    assert _save(client).status_code == 404


def test_the_form_shows_the_current_values_including_zero(client, db, staff):
    settings = get_business_settings(db)
    settings.min_lead_time_minutes = 0
    db.flush()
    _sign_in(client, staff)

    html = client.get("/barber/settings").text

    assert 'value="Asia/Tashkent"' in html
    assert 'name="min_lead_time_minutes" type="number" value="0"' in html


def test_saving_updates_every_setting(client, db, staff):
    _sign_in(client, staff)

    response = _save(client)

    assert response.status_code == 303
    settings = get_business_settings(db)
    db.refresh(settings)
    assert (settings.name, settings.timezone, settings.currency) == (
        "Barbershop Navbat",
        "Asia/Samarkand",
        "UZS",  # typed in lower case
    )
    assert (
        settings.slot_granularity_minutes,
        settings.min_lead_time_minutes,
        settings.max_booking_horizon_days,
        settings.cancellation_cutoff_hours,
    ) == (30, 0, 30, 4)


def test_an_unknown_timezone_is_refused_beside_the_field(client, db, staff):
    _sign_in(client, staff)

    response = _save(client, timezone="Mars/Olympus")

    assert response.status_code == 422
    assert "is not an IANA timezone" in response.text
    assert 'value="Mars/Olympus"' in response.text  # what was typed is kept
    assert get_business_settings(db).timezone == "Asia/Tashkent"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": "  "}, "name"),
        ({"currency": "SUM1"}, "currency"),
        ({"slot_granularity_minutes": "7"}, "slot_granularity_minutes"),
        ({"min_lead_time_minutes": "-1"}, "min_lead_time_minutes"),
        ({"max_booking_horizon_days": "0"}, "max_booking_horizon_days"),
        ({"max_booking_horizon_days": "400"}, "max_booking_horizon_days"),
        ({"cancellation_cutoff_hours": "1.5"}, "cancellation_cutoff_hours"),
    ],
)
def test_an_out_of_range_value_is_refused_and_nothing_is_saved(client, db, staff, overrides, field):
    _sign_in(client, staff)

    response = _save(client, **overrides)

    assert response.status_code == 422
    assert f'id="field-{field}-error"' in response.text
    assert get_business_settings(db).name == "Navbat"


def test_a_granularity_the_services_do_not_fit_is_refused_with_their_names(client, db, staff):
    db.add(Service(name="Beard trim", duration_minutes=45, price=1000))
    db.flush()
    _sign_in(client, staff)

    response = _save(client, slot_granularity_minutes="30")

    assert response.status_code == 409
    assert "Affected: Beard trim" in response.text
    assert get_business_settings(db).slot_granularity_minutes == 15
