"""A barber's photo: checked on the way in, stored on the provider row, served back.

Rules:
* JPEG, PNG or WebP only, recognised by the file's own first bytes (its
  signature). The file name and the Content-Type the client sent are typed by
  whoever uploads, so they are ignored; the stored type is the one the bytes
  prove. SVG is refused on purpose: it is a document that can carry script.
* At most `MAX_PHOTO_BYTES` (2 MB). `read_upload` reads one byte past the cap
  and stops, so an oversized upload is refused without being held in memory.
* Stored in Postgres next to the provider (ADR 0012), so there is no upload
  directory to back up or lose on redeploy. The CHECKs on `providers` repeat
  the type and size rules.
* Visible like the provider: an inactive provider's photo is the same 404 as a
  missing one for everyone but barbers.
* A new photo replaces the old one; removing a photo that is not there is a
  harmless no-op.

Errors: 404 `NOT_FOUND`; 413 `PHOTO_TOO_LARGE`; 415 `UNSUPPORTED_PHOTO`.
"""

from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.services.provider_catalog import ProviderView, get_provider

MAX_PHOTO_BYTES = 2 * 1024 * 1024

# What each accepted format's file starts with. WebP is a RIFF container: "RIFF",
# four bytes of length, then "WEBP".
_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"


def image_type(data: bytes) -> str | None:
    """The media type `data` really is, or None if it is not one we accept."""
    if data.startswith(_JPEG):
        return "image/jpeg"
    if data.startswith(_PNG):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_upload(stream: BinaryIO) -> bytes:
    """At most one byte more than the cap: enough to tell that a file is too big."""
    return stream.read(MAX_PHOTO_BYTES + 1)


def set_photo(db: Session, provider_id: int, data: bytes) -> ProviderView:
    """Store `data` as the provider's photo, replacing any earlier one.

    Raises:
        AppError: 404 `NOT_FOUND`; 413 `PHOTO_TOO_LARGE` over 2 MB; 415
            `UNSUPPORTED_PHOTO` when the bytes are not a JPEG, PNG or WebP
            (an empty file included). Nothing is changed on an error.
    """
    view = get_provider(db, provider_id, include_inactive=True)
    if len(data) > MAX_PHOTO_BYTES:
        raise AppError(
            "PHOTO_TOO_LARGE",
            "The photo is larger than 2 MB. Choose a smaller one.",
            status_code=413,
            details={"max_bytes": MAX_PHOTO_BYTES},
        )
    media_type = image_type(data)
    if media_type is None:
        raise AppError(
            "UNSUPPORTED_PHOTO",
            "The photo must be a JPEG, PNG or WebP image.",
            status_code=415,
        )
    view.provider.photo = data
    view.provider.photo_type = media_type
    db.flush()
    return view


def remove_photo(db: Session, provider_id: int) -> ProviderView:
    """Raises: 404 `NOT_FOUND`."""
    view = get_provider(db, provider_id, include_inactive=True)
    view.provider.photo = None
    view.provider.photo_type = None
    db.flush()
    return view


def get_photo(db: Session, provider_id: int, *, include_inactive: bool) -> tuple[bytes, str]:
    """The photo's bytes and media type.

    Raises: 404 `NOT_FOUND` for a missing provider, an inactive one when
    `include_inactive` is False, or a provider without a photo.
    """
    provider = get_provider(db, provider_id, include_inactive=include_inactive).provider
    if provider.photo_type is None:
        raise AppError("NOT_FOUND", "This provider has no photo.", status_code=404)
    return provider.photo, provider.photo_type
