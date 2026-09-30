"""Where a page may send the browser after a form: never off the site.

Login and register take a `next` address so a person lands back where they
were (for example the booking they started). Taken as-is, `next` is an *open
redirect*: a phishing link to our real login page with
`?next=https://evil.example` would forward a freshly signed-in victim to the
attacker's look-alike site.

So `next` must be a path on this site. Rejected:
- anything with a scheme or host: `https://evil.example`, `javascript:...`
- protocol-relative `//evil.example`, which browsers treat as another host
- backslashes: `/\\evil.example` is read as `//evil.example` by browsers
- whitespace and control characters: browsers strip tabs and newlines from
  URLs, so `/\\t/evil.example` would turn into `//evil.example`
"""

from urllib.parse import urlsplit

DEFAULT_NEXT = "/"


def safe_next_path(value: str | None) -> str:
    """`value` if it is a same-site path, else the home page."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return DEFAULT_NEXT
    if any(char == "\\" or ord(char) <= 0x20 or ord(char) == 0x7F for char in value):
        return DEFAULT_NEXT
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return DEFAULT_NEXT
    return value
