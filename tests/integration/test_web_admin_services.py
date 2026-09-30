"""Services admin pages (P9.2): access, create, edit, validation, activate."""

import pytest

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import Service
from app.models.user import User, UserRole
from app.web.templating import FLASH_COOKIE
from tests.integration.test_web_admin_dashboard import NOW

CSRF = "test-csrf-token"


def _user(db, role) -> User:
    user = User(email=f"{role.value}@example.com", password_hash="x", full_name="T P", role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def staff(db) -> User:
    return _user(db, UserRole.ADMIN)


def _sign_in(client, user) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, NOW))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _post(client, path, **data):
    return client.post(path, data={"csrf_token": CSRF, **data}, follow_redirects=False)


def _form(**overrides):
    return {
        "name": "Beard trim",
        "description": "Shape and tidy.",
        "duration_minutes": "30",
        "price": "40000",
    } | overrides


@pytest.fixture
def haircut(db) -> Service:
    service = Service(name="Haircut", duration_minutes=30, price=60_000)
    db.add(service)
    db.flush()
    return service


def test_a_customer_gets_404_and_a_visitor_a_login_redirect(client, db):
    assert client.get("/admin/services", follow_redirects=False).status_code == 303
    _sign_in(client, _user(db, UserRole.CUSTOMER))

    assert client.get("/admin/services").status_code == 404
    assert _post(client, "/admin/services", **_form()).status_code == 404


def test_the_list_includes_inactive_services(client, db, staff, haircut):
    db.add(Service(name="Old shave", duration_minutes=30, price=1, is_active=False))
    db.flush()
    _sign_in(client, staff)

    html = client.get("/admin/services").text

    assert "Haircut" in html and "Old shave" in html
    assert "Inactive" in html


def test_create_a_service_from_the_form(client, db, staff):
    _sign_in(client, staff)

    response = _post(client, "/admin/services", **_form())

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/services"
    service = db.query(Service).filter_by(name="Beard trim").one()
    assert (service.duration_minutes, service.price) == (30, 40_000)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": "   "}, "name"),
        ({"price": "12.5"}, "price"),
        ({"price": "-5"}, "price"),
        ({"duration_minutes": "abc"}, "duration_minutes"),
        ({"duration_minutes": "0"}, "duration_minutes"),
    ],
)
def test_a_bad_form_shows_the_error_and_keeps_what_was_typed(client, db, staff, overrides, field):
    _sign_in(client, staff)

    response = _post(client, "/admin/services", **_form(**overrides))

    assert response.status_code == 422
    assert f'id="field-{field}-error"' in response.text
    assert "Shape and tidy." in response.text
    assert db.query(Service).count() == 0


def test_a_duration_off_the_slot_grid_is_refused_beside_the_field(client, db, staff):
    _sign_in(client, staff)

    response = _post(client, "/admin/services", **_form(duration_minutes="20"))

    assert response.status_code == 422
    assert "multiple of 15 minutes" in response.text


def test_edit_changes_the_service(client, db, staff, haircut):
    _sign_in(client, staff)
    assert 'value="Haircut"' in client.get(f"/admin/services/{haircut.id}/edit").text

    response = _post(client, f"/admin/services/{haircut.id}", **_form(name="Cut", description=""))

    assert response.status_code == 303
    db.refresh(haircut)
    assert (haircut.name, haircut.description, haircut.price) == ("Cut", None, 40_000)


def test_edit_of_an_unknown_service_is_404(client, staff):
    _sign_in(client, staff)

    assert client.get("/admin/services/999999/edit").status_code == 404


def test_deactivate_then_activate(client, db, staff, haircut):
    _sign_in(client, staff)

    _post(client, f"/admin/services/{haircut.id}/deactivate")
    db.refresh(haircut)
    assert haircut.is_active is False

    response = _post(client, f"/admin/services/{haircut.id}/activate")
    db.refresh(haircut)
    assert haircut.is_active is True
    assert response.cookies.get(FLASH_COOKIE) == "service_activated"
