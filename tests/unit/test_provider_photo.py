"""Recognising a photo by its own bytes, and reading no more of an upload than needed."""

import io

import pytest

from app.services.provider_photo import MAX_PHOTO_BYTES, image_type, read_upload

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16


@pytest.mark.parametrize(
    ("data", "expected"),
    [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
)
def test_the_three_accepted_formats_are_recognised_by_their_first_bytes(data, expected):
    assert image_type(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"GIF89a" + b"\x00" * 16,
        b"RIFF\x24\x00\x00\x00WAVEfmt ",  # a RIFF file, but audio
        b"%PDF-1.7",
        b"hello, I am a .jpg file",
    ],
)
def test_anything_else_is_not_an_image_we_accept(data):
    assert image_type(data) is None


def test_reading_an_upload_stops_one_byte_past_the_cap():
    stream = io.BytesIO(b"x" * (MAX_PHOTO_BYTES * 3))

    assert len(read_upload(stream)) == MAX_PHOTO_BYTES + 1


def test_a_small_upload_is_read_whole():
    assert read_upload(io.BytesIO(JPEG)) == JPEG
