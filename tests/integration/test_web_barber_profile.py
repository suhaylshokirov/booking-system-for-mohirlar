"""A barber's own profile page (P9.3, reworked for ADR 0010): access, edit, offered
services, hide / show. The provider is the signed-in barber's own, never an address."""

import pytest

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import Provider, ProviderService, Service
from app.models.user import User, UserRole
from tests.integration.test_web_barber_dashboard import NOW
from tests.support import add_barber

CSRF = "test-csrf-token"


def _customer(db) -> User:
    user = User(email="c@example.com", password_hash="x", full_name="T P", role=UserRole.CUSTOMER)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def jasur(db) -> Provider:
    provider = Provider(name="Jasur", bio="Fades.")
    db.add(provider)
    db.flush()
    return provider


@pytest.fixture
def staff(db, jasur) -> User:
    """Jasur's own login."""
    return add_barber(db, "staff@example.com", "Jasur", provider=jasur)


def _sign_in(client, user) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, NOW))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _post(client, path, **data):
    return client.post(path, data={"csrf_token": CSRF, **data}, follow_redirects=False)


def _service(db, name, active=True) -> Service:
    service = Service(name=name, duration_minutes=30, price=1000, is_active=active)
    db.add(service)
    db.flush()
    return service


def _offered(db, provider) -> set[int]:
    rows = db.query(ProviderService).filter_by(provider_id=provider.id)
    return {row.service_id for row in rows}


def test_a_customer_gets_404_and_a_visitor_a_login_redirect(client, db):
    assert client.get("/barber/profile", follow_redirects=False).status_code == 303
    _sign_in(client, _customer(db))

    assert client.get("/barber/profile").status_code == 404
    assert _post(client, "/barber/profile", name="X").status_code == 404


def test_the_page_shows_the_barbers_own_profile_and_ticks_what_they_offer(client, db, staff, jasur):
    haircut, _ = _service(db, "Haircut"), _service(db, "Shave")
    db.add(ProviderService(provider_id=jasur.id, service_id=haircut.id))
    db.flush()
    _sign_in(client, staff)

    html = client.get("/barber/profile").text

    assert 'value="Jasur"' in html
    assert f'value="{haircut.id}" checked' in html
    assert "Hide me from customers" in html


def test_there_is_no_page_to_create_a_provider(client, staff):
    _sign_in(client, staff)

    assert client.get("/barber/providers").status_code == 404
    assert client.get("/barber/providers/new").status_code == 404
    assert _post(client, "/barber/providers", name="X").status_code in (404, 405)


def test_edit_replaces_the_offered_services(client, db, staff, jasur):
    haircut, shave = _service(db, "Haircut"), _service(db, "Shave")
    db.add(ProviderService(provider_id=jasur.id, service_id=haircut.id))
    db.flush()
    _sign_in(client, staff)

    response = _post(client, "/barber/profile", name="Jasur K", bio="New", service_ids=[shave.id])

    assert response.status_code == 303
    assert response.headers["location"] == "/barber/profile"
    db.refresh(jasur)
    assert (jasur.name, jasur.bio) == ("Jasur K", "New")
    assert _offered(db, jasur) == {shave.id}


def test_a_blank_name_shows_the_error_and_keeps_the_ticked_services(client, db, staff, jasur):
    haircut = _service(db, "Haircut")
    _sign_in(client, staff)

    response = _post(client, "/barber/profile", name="  ", service_ids=[haircut.id])

    assert response.status_code == 422
    assert 'id="field-name-error"' in response.text
    assert f'value="{haircut.id}" checked' in response.text
    db.refresh(jasur)
    assert jasur.name == "Jasur"


def test_unticking_everything_offers_nothing(client, db, staff, jasur):
    haircut = _service(db, "Haircut")
    db.add(ProviderService(provider_id=jasur.id, service_id=haircut.id))
    db.flush()
    _sign_in(client, staff)

    _post(client, "/barber/profile", name="Jasur")

    assert _offered(db, jasur) == set()


def test_a_service_deactivated_meanwhile_refuses_the_whole_save(client, db, staff, jasur):
    gone = _service(db, "Gone", active=False)
    _sign_in(client, staff)

    response = _post(client, "/barber/profile", name="Renamed", service_ids=[gone.id])

    assert response.status_code == 422
    assert "no longer active" in response.text
    db.refresh(jasur)
    assert jasur.name == "Jasur"


def test_hide_then_show_yourself(client, db, staff, jasur):
    _sign_in(client, staff)

    _post(client, "/barber/profile/deactivate")
    db.refresh(jasur)
    assert jasur.is_active is False
    assert "Show me to customers" in client.get("/barber/profile").text

    _post(client, "/barber/profile/activate")
    db.refresh(jasur)
    assert jasur.is_active is True


def test_one_barber_cannot_edit_another(client, db, staff):
    """The page always edits the signed-in barber's provider, whatever is posted."""
    other = Provider(name="Aziz")
    db.add(other)
    db.flush()
    _sign_in(client, staff)

    _post(client, "/barber/profile", name="Renamed", provider_id=other.id)
    _post(client, "/barber/profile/deactivate", provider_id=other.id)

    db.refresh(other)
    assert (other.name, other.is_active) == ("Aziz", True)
