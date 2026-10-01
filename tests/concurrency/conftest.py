"""Shared setup for the race tests: committed data and an app whose sessions really commit.

Frozen clock: 2026-10-01 07:00 UTC. Monday 2026-10-05, 10:00 Tashkent = 05:00 UTC.
"""

from datetime import time

import pytest

from app.core.clock import get_clock
from app.core.db import get_db
from app.core.security import create_access_token
from app.main import create_app
from app.models import AvailabilityRule, Provider, ProviderService, Service, User
from app.services.business_settings import get_business_settings


@pytest.fixture
def world(committing_db, frozen_clock):
    """Committed data: one service, two providers who offer it, and a factory for customers."""
    with committing_db() as db:
        # Commit the settings row up front. `get_business_settings` creates it on
        # first use, and a second transaction's insert would wait for the first to
        # commit, which the forced-interleaving barriers below would turn into a
        # deadlock that has nothing to do with bookings.
        get_business_settings(db)
        service = Service(name="Haircut", duration_minutes=30, price=60000)
        providers = [Provider(name="Jasur"), Provider(name="Aziz")]
        db.add(service)
        db.add_all(providers)
        db.flush()
        for provider in providers:
            db.add(ProviderService(provider_id=provider.id, service_id=service.id))
            db.add(
                AvailabilityRule(
                    provider_id=provider.id, weekday=0, start_time=time(9), end_time=time(12)
                )
            )
        db.commit()
        service_id, provider_ids = service.id, [p.id for p in providers]

    def new_customer(n: int) -> dict[str, str]:
        with committing_db() as db:
            user = User(
                email=f"customer{n}@example.com",
                full_name=f"Customer {n}",
            )
            db.add(user)
            db.commit()
            return {"Authorization": f"Bearer {create_access_token(user.id, frozen_clock.now())}"}

    return {"service_id": service_id, "provider_ids": provider_ids, "customer": new_customer}


@pytest.fixture
def app(committing_db, frozen_clock):
    app = create_app()

    def real_commit_session():
        # Same contract as the production `get_db`: commit on success, roll back on error.
        with committing_db() as db:
            yield db
            db.commit()

    app.dependency_overrides[get_db] = real_commit_session
    app.dependency_overrides[get_clock] = lambda: frozen_clock
    return app
