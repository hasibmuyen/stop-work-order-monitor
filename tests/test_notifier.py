from datetime import date

from stop_work_monitor.config import SmtpSettings
from stop_work_monitor.domain import StoredOrder
from stop_work_monitor.notifier import EmailNotifier


def test_notification_uses_singular_order_category(monkeypatch) -> None:
    settings = SmtpSettings(
        enabled=True,
        host="smtp.example.test",
        port=587,
        from_address="sender@example.test",
        to_addresses=["recipient@example.test"],
    )
    notifier = EmailNotifier(settings, "Stop work orders")
    messages = []
    monkeypatch.setattr(notifier, "_deliver", messages.append)

    notifier.send(
        StoredOrder(
            order_id=1,
            company_name="Example Pty Ltd",
            company_number="367595C",
            company_number_type="licence",
            order_added_on=date(2026, 11, 21),
            site_address="1 Example Street",
            source_url="https://example.test/order",
        )
    )

    assert messages[0]["Subject"] == "New Stop work order: Example Pty Ltd"
    assert "A new Stop work order has been recorded." in messages[0].get_content()
