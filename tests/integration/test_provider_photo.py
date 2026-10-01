"""A barber's photo through the API (P10.7): upload, serve, replace, remove, and who may."""

from sqlalchemy import inspect, select

from app.core.pagination import PageParams
from app.models import Provider
from app.services.provider_catalog import list_providers
from app.services.provider_photo import MAX_PHOTO_BYTES

PROVIDERS = "/api/v1/providers"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _upload(client, provider_id, data, headers, name="me.jpg", sent_type="image/jpeg"):
    return client.put(
        f"{PROVIDERS}/{provider_id}/photo",
        files={"photo": (name, data, sent_type)},
        headers=headers,
    )


def test_an_uploaded_photo_is_served_back_as_it_was_sent(client, barber):
    pid = barber.provider.id

    saved = _upload(client, pid, JPEG, barber)

    assert saved.status_code == 200
    url = saved.json()["photo_url"]
    assert url.startswith(f"/api/v1/providers/{pid}/photo?v=")
    photo = client.get(url)
    assert photo.status_code == 200
    assert photo.content == JPEG
    assert photo.headers["content-type"] == "image/jpeg"
    assert photo.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"{PROVIDERS}/{pid}").json()["photo_url"] == url


def test_the_type_is_judged_by_the_bytes_not_the_name_or_the_header(client, barber):
    pid = barber.provider.id

    _upload(client, pid, PNG, barber, name="holiday.jpg", sent_type="image/jpeg")

    assert client.get(f"{PROVIDERS}/{pid}/photo").headers["content-type"] == "image/png"


def test_a_file_that_is_not_a_jpeg_png_or_webp_is_415_and_changes_nothing(client, barber, db):
    pid = barber.provider.id
    _upload(client, pid, JPEG, barber)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    for data, name, sent_type in [
        (svg, "me.svg", "image/svg+xml"),
        (svg, "me.jpg", "image/jpeg"),  # lying about it does not help
        (b"", "empty.jpg", "image/jpeg"),
    ]:
        response = _upload(client, pid, data, barber, name=name, sent_type=sent_type)
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "UNSUPPORTED_PHOTO"

    assert client.get(f"{PROVIDERS}/{pid}/photo").content == JPEG


def test_a_photo_over_2_mb_is_413_and_one_of_exactly_2_mb_is_fine(client, barber):
    pid = barber.provider.id
    padding = MAX_PHOTO_BYTES - len(JPEG)

    too_big = _upload(client, pid, JPEG + b"\x00" * (padding + 1), barber)
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "PHOTO_TOO_LARGE"
    assert too_big.json()["error"]["details"] == {"max_bytes": MAX_PHOTO_BYTES}
    assert client.get(f"{PROVIDERS}/{pid}").json()["photo_url"] is None

    assert _upload(client, pid, JPEG + b"\x00" * padding, barber).status_code == 200


def test_a_new_photo_replaces_the_old_one(client, barber):
    pid = barber.provider.id
    _upload(client, pid, JPEG, barber)

    _upload(client, pid, PNG, barber)

    assert client.get(f"{PROVIDERS}/{pid}/photo").content == PNG


def test_removing_the_photo_and_removing_it_again(client, barber):
    pid = barber.provider.id
    _upload(client, pid, JPEG, barber)

    removed = client.delete(f"{PROVIDERS}/{pid}/photo", headers=barber)

    assert removed.status_code == 200
    assert removed.json()["photo_url"] is None
    missing = client.get(f"{PROVIDERS}/{pid}/photo")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert client.delete(f"{PROVIDERS}/{pid}/photo", headers=barber).status_code == 200


def test_only_the_barber_themselves_can_change_their_photo(client, barber, customer, db):
    other = Provider(name="Aziz")
    db.add(other)
    db.flush()

    assert _upload(client, other.id, JPEG, barber).status_code == 403
    assert client.delete(f"{PROVIDERS}/{other.id}/photo", headers=barber).status_code == 403
    assert _upload(client, barber.provider.id, JPEG, customer).status_code == 403
    assert _upload(client, barber.provider.id, JPEG, {}).status_code == 401
    db.refresh(other)
    assert other.photo_type is None


def test_a_hidden_barbers_photo_is_404_for_the_public_but_not_for_barbers(client, barber, db):
    pid = barber.provider.id
    _upload(client, pid, JPEG, barber)
    client.post(f"{PROVIDERS}/{pid}/deactivate", headers=barber)

    assert client.get(f"{PROVIDERS}/{pid}/photo").status_code == 404
    assert client.get(f"{PROVIDERS}/{pid}/photo", headers=barber).status_code == 200


def test_unknown_provider_photo_is_404(client):
    assert client.get(f"{PROVIDERS}/999999/photo").status_code == 404


def test_listing_providers_does_not_load_the_photo_bytes(client, barber, db):
    """The bytes are deferred: a page of providers never reads megabytes of images."""
    _upload(client, barber.provider.id, JPEG, barber)
    db.expire_all()

    views, _ = list_providers(
        db, PageParams(limit=10, offset=0), include_inactive=False, service_id=None
    )

    assert views
    assert all("photo" in inspect(v.provider).unloaded for v in views)
    assert db.scalar(select(Provider.photo_type).where(Provider.id == barber.provider.id))
