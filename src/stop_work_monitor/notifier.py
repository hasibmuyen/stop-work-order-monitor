"""Send one plain-text email for each newly recorded Stop Work Order."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from stop_work_monitor.config import SmtpSettings
from stop_work_monitor.domain import StoredOrder

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, settings: SmtpSettings) -> None:
        self._settings = settings

    def send(self, order: StoredOrder) -> None:
        if not self._settings.enabled:
            raise RuntimeError("Email is disabled")
        message = EmailMessage()
        added = order.order_added_on.isoformat()
        number = order.company_number or "Not stated on the order"
        lines = [
            "A new Stop Work Order has been recorded.",
            "",
            f"Company name: {order.company_name}",
            f"Company number: {number}",
            f"Company number type: {order.company_number_type}",
            f"Date added: {added}",
        ]
        lines.extend(
            [
                f"Site address: {order.site_address}",
                f"Register page: {order.source_url}",
            ]
        )
        message["Subject"] = f"New Stop Work Order: {order.company_name}"
        message["From"] = self._settings.from_address
        message["To"] = ", ".join(self._settings.to_addresses)
        message.set_content("\n".join(lines))
        self._deliver(message)
        logger.info("Sent Stop Work Order notification for %s", order.company_name)

    def _deliver(self, message: EmailMessage) -> None:
        settings = self._settings
        if settings.use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.host, settings.port, timeout=30)
        else:
            server = smtplib.SMTP(settings.host, settings.port, timeout=30)
        try:
            server.ehlo()
            if settings.use_tls:
                server.starttls()
                server.ehlo()
            password = settings.password.get_secret_value()
            if settings.username:
                server.login(settings.username, password)
            server.send_message(message)
        finally:
            server.quit()
