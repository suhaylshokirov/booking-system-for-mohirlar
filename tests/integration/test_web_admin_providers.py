"""Providers admin pages (P9.3): access, create, edit, offered services, activate."""

import pytest

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import Provider, ProviderService, Service
from app.models.user import User, UserRole
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


def _service(db, name, active=True) -> Service:
    service = Service(name=name, duration_minutes=30, price=1000, is_active=active)
    db.add(service)
    db.flush()
    return service


def _offered(db, provider) -> set[int]:
    rows = db.query(ProviderService).filter_by(provider_id=provider.id)
    return {row.service_id for row in rows}


@pytest.fixture
def jasur(db) -> Provider:
    provider = Provider(name="Jasur", bio="Fades.")
    db.add(provider)
    db.flush()
    return provider


def test_a_customer_gets_404_and_a_visitor_a_login_redirect(client, db):
    assert client.get("/admin/providers", follow_redirects=False).status_code == 303
    _sign_in(client, _user(db, UserRole.CUSTOMER))

    assert client.get("/admin/providers").status_code == 404
    assert _post(client, "/admin/providers", name="X").status_code == 404


def test_the_list_shows_inactive_providers_and_what_each_offers(client, db, staff, jasur):
    haircut = _service(db, "Haircut")
    db.add(ProviderService(provider_id=jasur.id, service_id=haircut.id))
    db.add(Provider(name="Old Timer", is_active=False))
    db.flush()
    _sign_in(client, staff)

    html = client.get("/admin/providers").text

    assert "Jasur" in html and "Old Timer" in html
    assert "Haircut" in html
    assert "Inactive" in html


def test_create_a_provider_with_services(client, db, staff):
    haircut, shave = _service(db, "Haircut"), _service(db, "Shave")
    _service(db, "Skipped")
    _sign_in(client, staff)

    response = _post(
        client, "/admin/providers", name=" Aziz ", bio="", service_ids=[haircut.id, shave.id]
    )

    assert response.status_code == 303
    provider = db.query(Provider).filter_by(name="Aziz").one()
    assert provider.bio is None
    assert _offered(db, provider) == {haircut.id, shave.id}


def test_a_blank_name_shows_the_error_and_keeps_the_ticked_services(client, db, staff):
    haircut = _service(db, "Haircut")
    _sign_in(client, staff)

    response = _post(client, "/admin/providers", name="  ", service_ids=[haircut.id])

    assert response.status_code == 422
    assert 'id="field-name-error"' in response.text
    assert f'value="{haircut.id}" checked' in response.text
    assert db.query(Provider).count() == 0


def test_edit_replaces_the_offered_services(client, db, staff, jasur):
    haircut, shave = _service(db, "Haircut"), _service(db, "Shave")
    db.add(ProviderService(provider_id=jasur.id, service_id=haircut.id))
    db.flush()
    _sign_in(client, staff)
    assert f'value="{haircut.id}" checked' in client.get(f"/admin/providers/{jasur.id}/edit").text

    response = _post(
        client, f"/admin/providers/{jasur.id}", name="Jasur K", bio="New", service_ids=[shave.id]
    )

    assert response.status_code == 303
    db.refresh(jasur)
    assert (jasur.name, jasur.bio) == ("Jasur K", "New")
    assert _offered(db, jasur) == {shave.id}


def test_unticking_everything_offers_nothing(client, db, staff, jasur):
    haircut = _service(db, "Haircut")
    db.add(ProviderService(provider_id=jasur.id, service_id=haircut.id))
    db.flush()
    _sign_in(client, staff)

    _post(client, f"/admin/providers/{jasur.id}", name="Jasur")

    assert _offered(db, jasur) == set()


def test_a_service_deactivated_meanwhile_refuses_the_whole_save(client, db, staff, jasur):
    gone = _service(db, "Gone", active=False)
    _sign_in(client, staff)

    response = _post(client, f"/admin/providers/{jasur.id}", name="Renamed", service_ids=[gone.id])

    assert response.status_code == 422
    assert "no longer active" in response.text
    db.refresh(jasur)
    assert jasur.name == "Jasur"


def test_edit_of_an_unknown_provider_is_404(client, staff):
    _sign_in(client, staff)

    assert client.get("/admin/providers/999999/edit").status_code == 404


def test_deactivate_then_activate(client, db, staff, jasur):
    _sign_in(client, staff)

    _post(client, f"/admin/providers/{jasur.id}/deactivate")
    db.refresh(jasur)
    assert jasur.is_active is False

    _post(client, f"/admin/providers/{jasur.id}/activate")
    db.refresh(jasur)
    assert jasur.is_active is True
