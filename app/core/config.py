"""Application settings, read from environment variables (and a local `.env`).

Every variable listed in `.env.example` has a field here. Defaults match
`.env.example` so the app and the tests start on a fresh checkout; production
must override the secrets, and refuses to start if it doesn't.
"""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The placeholder shipped in .env.example. Anyone can read it in the repo, so a
# production deployment using it would have forgeable tokens.
_PLACEHOLDER_JWT_SECRET = "change-me-to-a-long-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"

    database_url: str = "postgresql+psycopg://navbat:navbat@localhost:5433/navbat"
    test_database_url: str = "postgresql+psycopg://navbat:navbat@localhost:5433/navbat_test"

    jwt_secret: str = _PLACEHOLDER_JWT_SECRET
    jwt_expire_minutes: int = 720
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300

    # The first barber: the default of scripts/create_barber.py, and the demo barber
    # the seed script creates (and the login page's demo shortcut signs in as).
    barber_email: str = "jasur@navbat.local"

    # Email for the sign-in codes. Unset SMTP_HOST means "log the message to the
    # console" (development, tests); production requires it (validated below).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str = ""
    smtp_from: str = "Navbat <no-reply@navbat.local>"
    # starttls: connect plain, then upgrade (port 587). ssl: encrypted from the
    # start (port 465). none: no encryption, only for a local test server.
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"

    # Docker entrypoint: run `python -m scripts.seed` before starting the app.
    seed_demo_data: bool = False

    @model_validator(mode="after")
    def _reject_placeholder_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and self.jwt_secret == _PLACEHOLDER_JWT_SECRET:
            raise ValueError("JWT_SECRET must be changed from the placeholder in production")
        if self.app_env == "production" and not self.smtp_host:
            raise ValueError("SMTP_HOST must be set in production: sign-in codes are emailed")
        return self


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process; tests that need other values override
    the FastAPI dependency instead of mutating the environment."""
    return Settings()
