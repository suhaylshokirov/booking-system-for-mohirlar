"""The create-admin script (P2.6), run through its real entry point."""

from contextlib import nullcontext

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import PLACEHOLDER_ADMIN_PASSWORD, Settings
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from scripts import create_admin

EMAIL = "owner@example.com"
PASSWORD = "a long passphrase"


@pytest.fixture(autouse=True)
def _script_uses_the_test_session(db: Session, monkeypatch):
    """`main()` opens its own session; hand it the rolled-back test one instead."""
    monkeypatch.setattr(create_admin, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(create_admin, "get_settings", lambda: Settings(app_env="test"))


def _run(*args: str) -> int:
    return create_admin.main(list(args))


def _admins(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.role == UserRole.ADMIN)))


def test_creates_an_admin_who_can_log_in(db, client, capsys):
    assert _run("--email", EMAIL, "--password", PASSWORD) == 0

    [admin] = _admins(db)
    assert admin.email == EMAIL
    assert admin.is_active
    assert "Created admin owner@example.com" in capsys.readouterr().out
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 200
    me = client.get("/api/v1/auth/me")
    assert me.json()["role"] == "admin"


def test_rerunning_does_not_duplicate_or_change_anything(db, capsys):
    _run("--email", EMAIL, "--password", PASSWORD)
    first_hash = _admins(db)[0].password_hash
    capsys.readouterr()

    assert _run("--email", EMAIL.upper(), "--password", PASSWORD) == 0

    assert db.scalar(select(func.count()).select_from(User)) == 1
    assert _admins(db)[0].password_hash == first_hash  # not even re-salted
    assert "Nothing changed" in capsys.readouterr().out


def test_an_existing_customer_is_promoted_and_keeps_their_name(db):
    customer = User(
        email=EMAIL,
        password_hash=hash_password("old password"),
        full_name="Aziza Karimova",
        role=UserRole.CUSTOMER,
    )
    db.add(customer)
    db.flush()

    assert _run("--email", "Owner@Example.com", "--password", PASSWORD) == 0

    assert db.scalar(select(func.count()).select_from(User)) == 1
    db.refresh(customer)
    assert customer.role == UserRole.ADMIN
    assert customer.full_name == "Aziza Karimova"
    assert verify_password(PASSWORD, customer.password_hash)


def test_a_deactivated_account_is_reactivated(db):
    _run("--email", EMAIL, "--password", PASSWORD)
    admin = _admins(db)[0]
    admin.is_active = False
    db.flush()

    assert _run("--email", EMAIL, "--password", PASSWORD) == 0

    db.refresh(admin)
    assert admin.is_active


def test_rerunning_with_a_new_password_resets_it(db):
    _run("--email", EMAIL, "--password", PASSWORD)

    assert _run("--email", EMAIL, "--password", "a different passphrase") == 0

    [admin] = _admins(db)
    assert verify_password("a different passphrase", admin.password_hash)
    assert not verify_password(PASSWORD, admin.password_hash)


def test_falls_back_to_the_environment_settings(db, monkeypatch):
    settings = Settings(
        app_env="test", admin_email="env-admin@example.com", admin_password=PASSWORD
    )
    monkeypatch.setattr(create_admin, "get_settings", lambda: settings)

    assert _run() == 0

    assert [a.email for a in _admins(db)] == ["env-admin@example.com"]


@pytest.mark.parametrize(
    "email,password",
    [
        (EMAIL, "short"),  # under 8 characters
        (EMAIL, "x" * 129),
        ("not-an-email", PASSWORD),
    ],
)
def test_refuses_weak_passwords_and_bad_emails(db, capsys, email, password):
    assert _run("--email", email, "--password", password) == 1

    assert _admins(db) == []
    assert "Invalid admin details" in capsys.readouterr().err


def test_refuses_the_public_placeholder_password_in_production(db, capsys, monkeypatch):
    production = Settings(app_env="production", jwt_secret="x" * 40)
    monkeypatch.setattr(create_admin, "get_settings", lambda: production)

    assert _run("--email", EMAIL, "--password", PLACEHOLDER_ADMIN_PASSWORD) == 1

    assert _admins(db) == []
    assert "placeholder" in capsys.readouterr().err
    # ...while any real password is fine there.
    assert _run("--email", EMAIL, "--password", PASSWORD) == 0


def test_registration_still_cannot_create_an_admin(client, db):
    """The script is the only way in: an endpoint asking for it gets a customer."""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "full_name": "X", "role": "admin"},
    )
    assert response.json()["role"] == "customer"
    assert _admins(db) == []
