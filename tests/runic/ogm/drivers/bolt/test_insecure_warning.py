"""``_warn_if_insecure`` flags cleartext and unverified-TLS Bolt URIs."""

from __future__ import annotations

import logging

import pytest

from runic.ogm.driver.bolt import _warn_if_insecure

_LOGGER = "runic.ogm.driver.bolt"


def test_cleartext_remote_host_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _warn_if_insecure("bolt://db.example:7687")
    assert "not encrypted" in caplog.text


@pytest.mark.parametrize(
    "uri",
    ["bolt://localhost:7687", "bolt://127.0.0.1:7687", "bolt://[::1]:7687"],
)
def test_cleartext_loopback_is_silent(
    uri: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _warn_if_insecure(uri)
    assert caplog.text == ""


def test_verified_tls_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _warn_if_insecure("bolt+s://db.example:7687")
    assert caplog.text == ""


def test_unverified_tls_warns_even_on_loopback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _warn_if_insecure("bolt+ssc://localhost:7687")
    assert "certificate verification" in caplog.text


def test_credentials_in_uri_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _warn_if_insecure("bolt+ssc://user:hunter2@db.example:7687")
    assert "hunter2" not in caplog.text
