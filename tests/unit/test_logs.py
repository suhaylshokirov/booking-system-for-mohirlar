"""The app's `navbat.*` log lines reach standard error (they are the dev view of emailed codes)."""

import io
import logging

from app.core.logs import APP_LOGGER, configure_app_logging


def test_navbat_loggers_get_one_handler_however_often_it_is_called():
    logger = logging.getLogger(APP_LOGGER)
    configure_app_logging()
    configure_app_logging()

    assert len(logger.handlers) == 1
    assert logging.getLogger("navbat.mail").getEffectiveLevel() == logging.INFO


def test_a_mail_log_line_is_written_through_the_handler():
    configure_app_logging()
    [handler] = logging.getLogger(APP_LOGGER).handlers
    stream, handler.stream = handler.stream, io.StringIO()  # stand-in for standard error
    try:
        logging.getLogger("navbat.mail").info("email to a@example.com: hello")
        written = handler.stream.getvalue()
    finally:
        handler.stream = stream

    assert "[navbat.mail] email to a@example.com: hello" in written
