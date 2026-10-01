"""Sending a plain-text email: SMTP in production, the console otherwise.

The sign-in code is the only message sent through here (booking notices go
through the outbox, ADR 0009, because they must commit or roll back with the
booking; a code has no such coupling). Business code asks for a `Mailer` and
calls `send`; it never opens a connection itself, so tests inject a fake and
check what would have been sent.

`SmtpMailer` uses only the standard library (`smtplib`), so there is no new
dependency. Which mailer is used follows the settings: `SMTP_HOST` set means
SMTP, unset means `ConsoleMailer`, which logs the message so development and
tests need no mail server. Production refuses to start without `SMTP_HOST`
(`config.py`): an app that cannot send codes cannot sign anyone in.

Errors raised: `MailError` when the message could not be delivered to the
server (not reachable, refused, wrong credentials). It says nothing about
whether the person ever reads it: SMTP only reports hand-off.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger("navbat.mail")

# A mail server that does not answer must not hold a request open for minutes.
SMTP_TIMEOUT_SECONDS = 10


class MailError(Exception):
    """The message could not be handed to the mail server."""


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, mail: Mail) -> None:
        """Deliver `mail` or raise `MailError`."""


class ConsoleMailer:
    """Logs the message. For development: the sign-in code appears in the app's output."""

    def send(self, mail: Mail) -> None:
        logger.info("email to %s: %s\n%s", mail.to, mail.subject, mail.body)


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build(self, mail: Mail) -> EmailMessage:
        """The wire message. Separate from `send` so it can be checked without a server."""
        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = mail.to
        message["Subject"] = mail.subject
        # Transport headers, not business time: servers and spam filters expect them.
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(domain="navbat")
        message.set_content(mail.body)
        return message

    def send(self, mail: Mail) -> None:
        settings = self._settings
        message = self.build(mail)
        try:
            if settings.smtp_security == "ssl":
                connection = smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=SMTP_TIMEOUT_SECONDS,
                    context=ssl.create_default_context(),
                )
            else:
                connection = smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
                )
            with connection:
                if settings.smtp_security == "starttls":
                    connection.starttls(context=ssl.create_default_context())
                if settings.smtp_user:
                    connection.login(settings.smtp_user, settings.smtp_password)
                connection.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            # The cause (host, credentials) goes to the log, not to the person.
            logger.error("could not send email to %s: %s", mail.to, exc)
            raise MailError("The email could not be sent.") from exc


def build_mailer(settings: Settings) -> Mailer:
    return SmtpMailer(settings) if settings.smtp_host else ConsoleMailer()


def get_mailer() -> Mailer:
    """FastAPI dependency. Tests override it with a fake that records messages."""
    return build_mailer(get_settings())
