"""Send one plain-text email for each newly recorded Stop Work Order."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from stop_work_monitor.config import SmtpSettings
from stop_work_monitor.domain import StoredOrder

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, settings: SmtpSettings, order_category: str) -> None:
        self._settings = settings
        self._order_category = order_category.removesuffix("s")

    def send(self, order: StoredOrder) -> None:
        if not self._settings.enabled:
            raise RuntimeError("Email is disabled")
        message = EmailMessage()
        order_type = self._order_category
        added = order.order_added_on.isoformat()
        number = order.company_number or "Not stated on the order"
        company_number_type_label = "ACN" if order.company_number_type == "acn" else "License No."
        lines = [
            f"A new {order_type} has been recorded.",
            "",
            f"Company name: {order.company_name}",
            f"{company_number_type_label}: {number}",            
            f"Date added: {added}",
        ]
        lines.extend(
            [
                f"Site address: {order.site_address}",
                f"Register page: {order.source_url}",
            ]
        )
        message["Subject"] = f"New {order_type}: {order.company_name}"
        message["From"] = self._settings.from_address
        message["To"] = ", ".join(self._settings.to_addresses)
        message.set_content("\n".join(lines))
        self._deliver(message)
        logger.info(f"Sent {order_type} notification for {order.company_name}")

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
