"""Sending email: the SMTP conversation, the console fallback, and the settings that choose."""

import logging
import smtplib

import pytest

from app.core.config import Settings
from app.core.mail import ConsoleMailer, Mail, MailError, SmtpMailer, build_mailer

MAIL = Mail(to="aziza@example.com", subject="Your code", body="Your code is 123456.")


class FakeSmtp:
    """Stands in for smtplib.SMTP / SMTP_SSL and records the conversation."""

    instances: list["FakeSmtp"] = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSmtp.fail_with:
            raise FakeSmtp.fail_with
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[str] = []
        self.sent = None
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login {user}")

    def send_message(self, message):
        self.calls.append("send")
        self.sent = message


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.instances, FakeSmtp.fail_with = [], None
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp


def _settings(**overrides) -> Settings:
    return Settings(
        smtp_host="smtp.example.com", smtp_from="Navbat <no-reply@example.com>", **overrides
    )


def test_starttls_login_then_send():
    SmtpMailer(_settings(smtp_user="u", smtp_password="p")).send(MAIL)

    smtp = FakeSmtp.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.calls == ["starttls", "login u", "send", "quit"]
    assert smtp.timeout == 10  # a silent server must not hold the request open


def test_the_message_has_the_headers_and_body():
    SmtpMailer(_settings()).send(MAIL)

    message = FakeSmtp.instances[0].sent
    assert message["From"] == "Navbat <no-reply@example.com>"
    assert message["To"] == "aziza@example.com"
    assert message["Subject"] == "Your code"
    assert message["Date"] and message["Message-ID"]
    assert message.get_content().strip() == "Your code is 123456."


def test_ssl_mode_skips_starttls_and_no_user_skips_login():
    SmtpMailer(_settings(smtp_security="ssl", smtp_port=465)).send(MAIL)

    assert FakeSmtp.instances[0].calls == ["send", "quit"]
    assert FakeSmtp.instances[0].port == 465


def test_security_none_sends_in_the_clear_for_a_local_test_server():
    SmtpMailer(_settings(smtp_security="none", smtp_port=1025)).send(MAIL)

    assert FakeSmtp.instances[0].calls == ["send", "quit"]


@pytest.mark.parametrize(
    "failure", [smtplib.SMTPAuthenticationError(535, b"no"), ConnectionRefusedError()]
)
def test_a_server_problem_becomes_mail_error(failure, caplog):
    FakeSmtp.fail_with = failure
    with caplog.at_level(logging.ERROR, logger="navbat.mail"), pytest.raises(MailError):
        SmtpMailer(_settings()).send(MAIL)
    assert "could not send email to aziza@example.com" in caplog.text


def test_a_header_injection_attempt_cannot_add_headers():
    evil = Mail(to="a@example.com\nBcc: victim@example.com", subject="x", body="x")
    with pytest.raises(ValueError):
        SmtpMailer(_settings()).build(evil)


def test_settings_pick_the_mailer():
    assert isinstance(build_mailer(Settings()), ConsoleMailer)
    assert isinstance(build_mailer(_settings()), SmtpMailer)


def test_console_mailer_logs_the_message(caplog):
    with caplog.at_level(logging.INFO, logger="navbat.mail"):
        ConsoleMailer().send(MAIL)
    assert "aziza@example.com" in caplog.text and "123456" in caplog.text


def test_production_refuses_to_start_without_smtp():
    with pytest.raises(ValueError, match="SMTP_HOST"):
        Settings(app_env="production", jwt_secret="x" * 40)
    Settings(app_env="production", jwt_secret="x" * 40, smtp_host="smtp.example.com")
