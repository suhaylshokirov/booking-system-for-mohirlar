"""The services list (home page) and a service's page (P8.3)."""

import pytest
from sqlalchemy.orm import Session

from app.models.provider import Provider, ProviderService
from app.models.service import Service
from app.web.catalog import SERVICES_PER_PAGE
from app.web.formatting import NBSP


def _service(db: Session, name: str, **fields) -> Service:
    values = {"duration_minutes": 30, "price": 60_000, "description": None, **fields}
    service = Service(name=name, **values)
    db.add(service)
    db.flush()
    return service


def _provider(db: Session, name: str, offers: list[Service], **fields) -> Provider:
    provider = Provider(name=name, **fields)
    db.add(provider)
    db.flush()
    for service in offers:
        db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.flush()
    return provider


@pytest.fixture
def haircut(db: Session) -> Service:
    return _service(
        db,
        "Haircut",
        description="Classic scissor or clipper cut with a wash and style.",
        duration_minutes=45,
        price=60_000,
    )


# --- The list --------------------------------------------------------------------


def test_home_lists_active_services_with_duration_and_price(client, haircut):
    html = client.get("/").text

    assert '<span class="price-row__name">Haircut</span>' in html
    assert f"45{NBSP}min" in html
    assert f"60{NBSP}000{NBSP}UZS" in html
    assert "Classic scissor or clipper cut" in html
    assert f'href="/services/{haircut.id}"' in html


def test_inactive_services_are_not_listed(client, db, haircut):
    _service(db, "Hot towel shave", is_active=False)

    html = client.get("/").text

    assert "Haircut" in html
    assert "Hot towel shave" not in html


def test_empty_list_says_why_nothing_can_be_booked(client):
    html = client.get("/").text

    assert 'class="empty"' in html
    assert "listed its services" in html
    assert 'class="price-board"' not in html


def test_the_list_is_paged(client, db):
    for n in range(SERVICES_PER_PAGE + 1):
        _service(db, f"Service {n:02d}")

    first = client.get("/").text
    second = client.get("/", params={"page": 2}).text

    assert first.count('class="price-row"') == SERVICES_PER_PAGE
    assert 'href="/?page=2" rel="next"' in first
    assert second.count('class="price-row"') == 1
    assert 'href="/?page=1" rel="prev"' in second
    assert client.get("/", params={"page": 3}).status_code == 404


def test_a_single_page_has_no_pagination(client, haircut):
    assert 'class="pagination"' not in client.get("/").text


# --- A service's page ----------------------------------------------------------------


def test_service_page_shows_the_facts_and_who_offers_it(client, db, haircut):
    jasur = _provider(db, "Jasur", [haircut], bio="Ten years behind the chair.")
    _provider(db, "Dilshod", [])  # offers nothing

    html = client.get(f"/services/{haircut.id}").text

    assert '<h1 class="sheet-title">Haircut</h1>' in html
    assert f"45{NBSP}min" in html
    assert f"60{NBSP}000{NBSP}UZS" in html
    assert "Jasur" in html
    assert "Ten years behind the chair." in html
    assert "Dilshod" not in html
    assert f'href="/book/{haircut.id}">Book a time</a>' in html
    assert f'href="/book/{haircut.id}?provider={jasur.id}">Book with Jasur</a>' in html


def test_a_barbers_phone_is_a_tap_to_call_link_on_their_card(client, db, haircut):
    _provider(db, "Jasur", [haircut], phone="+998901234567")
    _provider(db, "Bekzod", [haircut])  # no number given

    html = client.get(f"/services/{haircut.id}").text

    grouped = "+998 90 123 45 67".replace(" ", NBSP)
    assert f'href="tel:+998901234567" aria-label="Call Jasur: {grouped}">{grouped}</a>' in html
    assert html.count('class="staff-card__phone') == 1


def test_a_barber_with_a_photo_is_shown_in_an_arch_and_one_without_by_initial(client, db, haircut):
    jasur = _provider(db, "Jasur", [haircut], photo=b"\xff\xd8\xff", photo_type="image/jpeg")
    _provider(db, "Bekzod", [haircut])

    html = client.get(f"/services/{haircut.id}").text

    assert f'<img src="/api/v1/providers/{jasur.id}/photo?v=' in html
    assert '<span class="arch__initial" aria-hidden="true">B</span>' in html


def test_inactive_staff_are_not_offered(client, db, haircut):
    _provider(db, "Jasur", [haircut])
    _provider(db, "Bekzod", [haircut], is_active=False)

    html = client.get(f"/services/{haircut.id}").text

    assert "Jasur" in html
    assert "Bekzod" not in html


def test_a_service_nobody_offers_cannot_be_booked(client, haircut):
    html = client.get(f"/services/{haircut.id}").text

    assert "Nobody offers this service right now" in html
    assert "Book a time" not in html


def test_inactive_service_page_is_a_404(client, db):
    retired = _service(db, "Hot towel shave", is_active=False)

    response = client.get(f"/services/{retired.id}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Service not found." in response.text


def test_unknown_service_page_is_a_404(client):
    assert client.get("/services/999999").status_code == 404


def test_malformed_service_id_is_an_html_page(client):
    response = client.get("/services/haircut")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
