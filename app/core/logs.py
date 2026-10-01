"""Make the app's own log lines visible.

Uvicorn configures only its own loggers, so a plain `logger.info(...)` from the
app is dropped. The app's loggers are all named `navbat.*` (`navbat.mail` shows
the sign-in code when no mail server is configured, `navbat.notifications` the
booking messages); this gives them one handler on standard error so
`docker compose logs` and the terminal show them.
"""

import logging

APP_LOGGER = "navbat"


def configure_app_logging() -> None:
    """Idempotent: calling it again (every `create_app()`, so every test) adds nothing."""
    logger = logging.getLogger(APP_LOGGER)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
