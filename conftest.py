"""Runs before `tests/conftest.py` and before any `app` module is imported.

A developer's `.env` may point at a real mail server (the live deploy's Gmail
account, say). Tests must never read it: an empty SMTP_HOST selects the console
mailer, and with no user the SMTP tests start from the defaults. Environment
variables outrank `.env`, and they have to be set here because `app/core/db.py`
calls the cached `get_settings()` while it is imported.
"""

import os

# Pinned to the defaults in app/core/config.py, so no value of the developer's
# own mail setup (port, security, sender) can reach a test either.
os.environ.update(
    SMTP_HOST="",
    SMTP_USER="",
    SMTP_PASSWORD="",
    SMTP_PORT="587",
    SMTP_FROM="Navbat <no-reply@navbat.local>",
    SMTP_SECURITY="starttls",
)
