import dataclasses
import smtplib

import pytest

from app.services import mailer


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, message):
        self.calls.append(("send", message["To"], message["From"], message["Subject"]))


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)


@pytest.fixture
def mail_settings(settings):
    return dataclasses.replace(
        settings, smtp_host="smtp.gmail.com", smtp_username="books@gmail.com", smtp_password="app-password"
    )


def test_sends_over_starttls_with_login(mail_settings):
    assert mailer.send_email(mail_settings, "a@example.test", "Hello", "Body") is True
    server = FakeSMTP.instances[0]
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert server.calls == [
        "starttls",
        ("login", "books@gmail.com"),
        ("send", "a@example.test", "books@gmail.com", "Hello"),
    ]


def test_ssl_mode_skips_starttls(mail_settings):
    mailer.send_email(
        dataclasses.replace(mail_settings, smtp_security="ssl", smtp_port=465), "a@example.test", "S", "B"
    )
    assert "starttls" not in FakeSMTP.instances[0].calls


def test_not_configured_means_no_email(settings):
    assert settings.mail_enabled is False
    assert mailer.send_email(settings, "a@example.test", "Hello", "Body") is False
    assert FakeSMTP.instances == []


def test_a_mail_server_problem_never_raises(mail_settings, monkeypatch):
    def broken(*_args, **_kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad password")

    monkeypatch.setattr(FakeSMTP, "login", broken)
    assert mailer.send_email(mail_settings, "a@example.test", "Hello", "Body") is False


def test_public_url_comes_from_settings(monkeypatch):
    from app.config import load_settings

    monkeypatch.setenv("DOMAIN", "optionscreener.online")
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    assert load_settings().public_url == "https://optionscreener.online"
    monkeypatch.setenv("PUBLIC_URL", "https://books.example.test/")
    assert load_settings().public_url == "https://books.example.test"
