"""Providers (the staff who perform services) and which services each offers.

Rules:
* Providers are deactivated, never deleted (bookings reference them). An
  inactive provider is invisible to everyone except admins: a customer gets the
  same 404 as for a provider that never existed.
* A provider's offered services are replaced as a whole set, and only *active*
  services can be offered.
* Deactivating a provider, or changing what they offer, never touches existing
  bookings: they keep their provider and service and stay in the history.

Every read returns `ProviderView`s so a provider always comes with the services
to show for them, and customers only ever see active services.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.pagination import PageParams, paginate
from app.models.provider import Provider, ProviderService
from app.models.service import Service


@dataclass
class ProviderView:
    """A provider and the services that should be shown with them."""

    provider: Provider
    services: list[Service]


def _not_found() -> AppError:
    return AppError("NOT_FOUND", "Provider not found.", status_code=404)


def _views(db: Session, providers: list[Provider], *, include_inactive: bool) -> list[ProviderView]:
    """Attach services to `providers` with one query, not one per provider."""
    by_provider: dict[int, list[Service]] = {p.id: [] for p in providers}
    if providers:
        query = (
            select(ProviderService.provider_id, Service)
            .join(Service, Service.id == ProviderService.service_id)
            .where(ProviderService.provider_id.in_(list(by_provider)))
            .order_by(Service.name, Service.id)
        )
        if not include_inactive:
            query = query.where(Service.is_active)
        for provider_id, service in db.execute(query):
            by_provider[provider_id].append(service)
    return [ProviderView(p, by_provider[p.id]) for p in providers]


def list_providers(
    db: Session, params: PageParams, *, include_inactive: bool, service_id: int | None
) -> tuple[list[ProviderView], int]:
    """One page of providers, alphabetical; active only unless `include_inactive`.

    With `service_id`, only providers offering that service. A service that is
    unknown, or inactive to this caller, simply matches nobody.
    """
    query = select(Provider).order_by(Provider.name, Provider.id)
    if not include_inactive:
        query = query.where(Provider.is_active)
    if service_id is not None:
        offers = (
            select(ProviderService.provider_id)
            .join(Service, Service.id == ProviderService.service_id)
            .where(ProviderService.service_id == service_id)
        )
        if not include_inactive:
            offers = offers.where(Service.is_active)
        query = query.where(Provider.id.in_(offers))
    providers, total = paginate(db, query, params)
    return _views(db, providers, include_inactive=include_inactive), total


def get_provider(db: Session, provider_id: int, *, include_inactive: bool) -> ProviderView:
    """Raises: 404 `NOT_FOUND` if missing, or inactive and `include_inactive` is False."""
    provider = db.get(Provider, provider_id)
    if provider is None or (not provider.is_active and not include_inactive):
        raise _not_found()
    return _views(db, [provider], include_inactive=include_inactive)[0]


def create_provider(db: Session, data: dict[str, Any]) -> ProviderView:
    """A new provider offers nothing until `replace_offered_services` says so."""
    provider = Provider(**data)
    db.add(provider)
    db.flush()
    return ProviderView(provider, [])


def update_provider(db: Session, provider_id: int, changes: dict[str, Any]) -> ProviderView:
    """Raises: 404 `NOT_FOUND`."""
    view = get_provider(db, provider_id, include_inactive=True)
    for field, value in changes.items():
        setattr(view.provider, field, value)
    db.flush()
    return view


def set_provider_active(db: Session, provider_id: int, *, active: bool) -> ProviderView:
    """Deactivate or reactivate. Repeating the current state is a harmless no-op.

    Raises: 404 `NOT_FOUND`.
    """
    view = get_provider(db, provider_id, include_inactive=True)
    view.provider.is_active = active
    db.flush()
    return view


def replace_offered_services(db: Session, provider_id: int, service_ids: list[int]) -> ProviderView:
    """Make `service_ids` exactly the set this provider offers.

    Repeated ids count once; an empty list means "offers nothing". The provider
    row is locked first, so two admins replacing the set at once run one after
    the other instead of interleaving into a mix of both.

    Raises:
        AppError: 404 `NOT_FOUND`; 422 `UNKNOWN_SERVICE` when any id is not an
            existing, active service (`details.service_ids` lists them, and
            nothing is changed).
    """
    provider = db.scalars(
        select(Provider).where(Provider.id == provider_id).with_for_update()
    ).one_or_none()
    if provider is None:
        raise _not_found()

    wanted = set(service_ids)
    usable = set(db.scalars(select(Service.id).where(Service.id.in_(wanted), Service.is_active)))
    if usable != wanted:
        raise AppError(
            "UNKNOWN_SERVICE",
            "Some of those services do not exist or are not active.",
            status_code=422,
            details={"service_ids": sorted(wanted - usable)},
        )

    db.execute(
        delete(ProviderService).where(
            ProviderService.provider_id == provider_id,
            ProviderService.service_id.not_in(wanted),
        )
    )
    if wanted:
        db.execute(
            insert(ProviderService)
            .values([{"provider_id": provider_id, "service_id": sid} for sid in wanted])
            .on_conflict_do_nothing()
        )
    db.flush()
    return _views(db, [provider], include_inactive=True)[0]
