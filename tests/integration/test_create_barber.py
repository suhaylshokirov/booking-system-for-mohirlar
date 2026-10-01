"""The create-barber script (P2.6), run through its real entry point."""

from contextlib import nullcontext

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.provider import Provider
from app.models.user import User, UserRole
from scripts import create_barber
from tests.support import api_sign_in

EMAIL = "owner@example.com"


@pytest.fixture(autouse=True)
def _script_uses_the_test_session(db: Session, monkeypatch):
    """`main()` opens its own session; hand it the rolled-back test one instead."""
    monkeypatch.setattr(create_barber, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(create_barber, "get_settings", lambda: Settings(app_env="test"))


def _run(*args: str) -> int:
    return create_barber.main(list(args))


def _barbers(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.role == UserRole.BARBER)))


def test_creates_a_barber_who_can_sign_in_with_a_code(db, client, mailbox, capsys):
    assert _run("--email", EMAIL) == 0

    [barber] = _barbers(db)
    assert barber.email == EMAIL
    assert barber.is_active
    # The barber's provider record is created with them, named after them.
    assert db.get(Provider, barber.provider_id).name == "Barber"
    assert "Created barber owner@example.com" in capsys.readouterr().out
    assert api_sign_in(client, mailbox, email=EMAIL).status_code == 200
    me = client.get("/api/v1/auth/me")
    assert me.json()["role"] == "barber"


def test_rerunning_does_not_duplicate_or_change_anything(db, capsys):
    _run("--email", EMAIL)
    capsys.readouterr()

    assert _run("--email", EMAIL.upper()) == 0

    assert db.scalar(select(func.count()).select_from(User)) == 1
    assert db.scalar(select(func.count()).select_from(Provider)) == 1  # no second provider
    assert "Nothing changed" in capsys.readouterr().out


def test_an_existing_customer_is_promoted_and_keeps_their_name(db):
    customer = User(
        email=EMAIL,
        full_name="Aziza Karimova",
        role=UserRole.CUSTOMER,
    )
    db.add(customer)
    db.flush()

    assert _run("--email", "Owner@Example.com") == 0

    assert db.scalar(select(func.count()).select_from(User)) == 1
    db.refresh(customer)
    assert customer.role == UserRole.BARBER
    assert customer.full_name == "Aziza Karimova"
    assert db.get(Provider, customer.provider_id).name == "Aziza Karimova"


def test_a_deactivated_account_is_reactivated(db):
    _run("--email", EMAIL)
    barber = _barbers(db)[0]
    barber.is_active = False
    db.flush()

    assert _run("--email", EMAIL) == 0

    db.refresh(barber)
    assert barber.is_active


def test_falls_back_to_the_environment_settings(db, monkeypatch):
    settings = Settings(app_env="test", barber_email="env-barber@example.com")
    monkeypatch.setattr(create_barber, "get_settings", lambda: settings)

    assert _run() == 0

    assert [a.email for a in _barbers(db)] == ["env-barber@example.com"]


@pytest.mark.parametrize("email", ["not-an-email", "a@b", ""])
def test_refuses_a_bad_email(db, capsys, email):
    assert _run("--email", email) == 1

    assert _barbers(db) == []
    assert "Invalid barber details" in capsys.readouterr().err


def test_there_is_no_password_flag(db, capsys):
    with pytest.raises(SystemExit):
        _run("--email", EMAIL, "--password", "whatever")

    assert _barbers(db) == []


def test_signing_up_still_cannot_create_a_barber(client, db, mailbox):
    """The script is the only way in: an endpoint asking for it gets a customer."""
    client.post("/api/v1/auth/register", json={"email": EMAIL, "full_name": "X", "role": "barber"})
    client.post("/api/v1/auth/verify", json={"email": EMAIL, "code": mailbox.last_code(EMAIL)})
    assert client.get("/api/v1/auth/me").json()["role"] == "customer"
    assert _barbers(db) == []


def test_the_name_flag_names_the_barber_and_their_provider(db):
    assert _run("--email", EMAIL, "--name", "Jasur") == 0

    [barber] = _barbers(db)
    assert barber.full_name == "Jasur"
    assert db.get(Provider, barber.provider_id).name == "Jasur"


def test_the_database_refuses_a_barber_without_a_provider_and_a_customer_with_one(db):
    """The rule lives in the schema, not only in the script (`ck_users_barber_has_provider`)."""
    from sqlalchemy.exc import IntegrityError

    provider = Provider(name="P")
    db.add(provider)
    db.flush()
    for role, provider_id in ((UserRole.BARBER, None), (UserRole.CUSTOMER, provider.id)):
        with pytest.raises(IntegrityError) as error, db.begin_nested():
            db.add(
                User(
                    email=f"{role.value}@example.com",
                    full_name="X",
                    role=role,
                    provider_id=provider_id,
                )
            )
            db.flush()
        assert "barber_has_provider" in str(error.value)


def test_two_barbers_cannot_share_one_provider(db):
    from sqlalchemy.exc import IntegrityError

    provider = Provider(name="P")
    db.add(provider)
    db.flush()
    db.add(
        User(
            email="a@example.com",
            full_name="A",
            role=UserRole.BARBER,
            provider_id=provider.id,
        )
    )
    db.flush()
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.add(
            User(
                email="b@example.com",
                full_name="B",
                role=UserRole.BARBER,
                provider_id=provider.id,
            )
        )
        db.flush()
    assert "uq_users_provider_id" in str(error.value)
