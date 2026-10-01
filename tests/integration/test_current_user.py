"""get_current_user, get_optional_user and require_barber (P2.3).

No barber-only or optional-auth endpoints exist yet, so these tests mount tiny
probe routes on a throwaway app. That exercises the real dependencies through
real HTTP requests, cookies and headers.
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import ACCESS_COOKIE, BarberUser, CurrentUser, OptionalUser
from app.core.clock import FrozenClock, get_clock
from app.core.db import get_db
from app.core.errors import register_error_handlers
from app.core.security import create_access_token
from app.models.provider import Provider
from app.models.user import User, UserRole


@pytest.fixture
def client(db: Session, frozen_clock: FrozenClock) -> Iterator[TestClient]:
    """Shadows the shared `client` fixture: same wiring, plus the probe routes."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/protected")
    def protected(user: CurrentUser) -> dict:
        return {"id": user.id}

    @app.get("/optional")
    def optional(user: OptionalUser) -> dict:
        return {"id": user.id if user else None}

    @app.get("/barber-only")
    def barber_only(user: BarberUser) -> dict:
        return {"id": user.id}

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: frozen_clock
    with TestClient(app) as test_client:
        yield test_client


def _provider(db: Session) -> Provider:
    provider = Provider(name="Barber")
    db.add(provider)
    db.flush()
    return provider


def _user(db: Session, role: UserRole = UserRole.CUSTOMER, **fields) -> User:
    if role == UserRole.BARBER and "provider_id" not in fields:
        fields["provider_id"] = _provider(db).id  # a barber always runs a provider
    user = User(
        email=fields.pop("email", f"{role.value}@example.com"),
        full_name="Test User",
        role=role,
        **fields,
    )
    db.add(user)
    db.flush()
    return user


def _bearer(user: User, clock: FrozenClock) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, clock.now())}"}


# --- get_current_user ------------------------------------------------------


def test_bearer_token_authenticates(client, db, frozen_clock):
    user = _user(db)
    response = client.get("/protected", headers=_bearer(user, frozen_clock))
    assert response.status_code == 200
    assert response.json() == {"id": user.id}


def test_cookie_authenticates(client, db, frozen_clock):
    user = _user(db)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, frozen_clock.now()))
    assert client.get("/protected").json() == {"id": user.id}


def test_bearer_wins_over_the_cookie(client, db, frozen_clock):
    bearer_user = _user(db, email="bearer@example.com")
    cookie_user = _user(db, email="cookie@example.com")
    client.cookies.set(ACCESS_COOKIE, create_access_token(cookie_user.id, frozen_clock.now()))

    response = client.get("/protected", headers=_bearer(bearer_user, frozen_clock))

    assert response.json() == {"id": bearer_user.id}


def test_anonymous_is_401(client):
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_deactivated_user_with_a_valid_token_is_401(client, db, frozen_clock):
    user = _user(db)
    headers = _bearer(user, frozen_clock)
    assert client.get("/protected", headers=headers).status_code == 200

    user.is_active = False
    db.flush()

    response = client.get("/protected", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


def test_token_for_a_user_that_no_longer_exists_is_401(client, db, frozen_clock):
    user = _user(db)
    headers = _bearer(user, frozen_clock)
    db.delete(user)
    db.flush()

    response = client.get("/protected", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


# --- require_barber ---------------------------------------------------------


def test_barber_passes(client, db, frozen_clock):
    barber = _user(db, UserRole.BARBER)
    response = client.get("/barber-only", headers=_bearer(barber, frozen_clock))
    assert response.status_code == 200
    assert response.json() == {"id": barber.id}


def test_customer_on_a_barber_route_is_403(client, db, frozen_clock):
    customer = _user(db)
    response = client.get("/barber-only", headers=_bearer(customer, frozen_clock))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_anonymous_on_a_barber_route_is_401_not_403(client):
    """403 would tell a stranger the route exists and needs a role; 401 asks them to log in."""
    response = client.get("/barber-only")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_role_changes_apply_to_tokens_already_issued(client, db, frozen_clock):
    """The role comes from the database, not the token."""
    user = _user(db)
    headers = _bearer(user, frozen_clock)
    assert client.get("/barber-only", headers=headers).status_code == 403

    user.role, user.provider_id = UserRole.BARBER, _provider(db).id
    db.flush()
    assert client.get("/barber-only", headers=headers).status_code == 200

    user.role, user.provider_id = UserRole.CUSTOMER, None
    db.flush()
    assert client.get("/barber-only", headers=headers).status_code == 403


def test_deactivated_barber_is_locked_out(client, db, frozen_clock):
    barber = _user(db, UserRole.BARBER)
    headers = _bearer(barber, frozen_clock)
    barber.is_active = False
    db.flush()

    response = client.get("/barber-only", headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (401, "ACCOUNT_INACTIVE")


# --- get_optional_user -----------------------------------------------------


def test_optional_user_is_none_for_anonymous(client):
    response = client.get("/optional")
    assert response.status_code == 200
    assert response.json() == {"id": None}


def test_optional_user_is_the_user_when_logged_in(client, db, frozen_clock):
    user = _user(db)
    assert client.get("/optional", headers=_bearer(user, frozen_clock)).json() == {"id": user.id}


def test_optional_user_treats_a_bad_token_as_anonymous(client):
    response = client.get("/optional", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 200
    assert response.json() == {"id": None}


def test_optional_user_treats_an_expired_session_as_anonymous(client, db, frozen_clock):
    user = _user(db)
    headers = _bearer(user, frozen_clock)
    frozen_clock.advance(timedelta(days=2))

    assert client.get("/optional", headers=headers).json() == {"id": None}


def test_optional_user_treats_a_deactivated_user_as_anonymous(client, db, frozen_clock):
    user = _user(db, is_active=False)
    assert client.get("/optional", headers=_bearer(user, frozen_clock)).json() == {"id": None}
