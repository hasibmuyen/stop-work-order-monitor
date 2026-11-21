import pytest
from pydantic import ValidationError

from stop_work_monitor.config import SmtpSettings


def _smtp_settings(**overrides: object) -> SmtpSettings:
    values: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 587,
        "from_address": "sender@example.com",
        "to_addresses": ["recipient@example.com"],
    }
    values.update(overrides)
    return SmtpSettings.model_validate(values)


def test_smtp_settings_accept_valid_sender_and_recipients() -> None:
    settings = _smtp_settings(
        from_address=" sender@example.com ",
        to_addresses=[" recipient@example.com ", "other@example.com"],
    )

    assert str(settings.from_address) == "sender@example.com"
    assert [str(address) for address in settings.to_addresses] == [
        "recipient@example.com",
        "other@example.com",
    ]


@pytest.mark.parametrize("from_address", ["", "not-an-email", "sender@"])
def test_smtp_settings_reject_invalid_sender(from_address: str) -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(from_address=from_address)


@pytest.mark.parametrize(
    "to_addresses",
    [["not-an-email"], ["valid@example.com", ""], ["valid@example.com", "recipient@"]],
)
def test_smtp_settings_reject_invalid_recipient(to_addresses: list[str]) -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(to_addresses=to_addresses)
