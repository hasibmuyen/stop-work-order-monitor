"""Poll the register, store unseen Stop Work Orders, and notify recipients."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from stop_work_monitor.config import Settings
from stop_work_monitor.domain import StoredOrder
from stop_work_monitor.notifier import EmailNotifier
from stop_work_monitor.parsing import build_parsed_order
from stop_work_monitor.repository import OrderRepository
from stop_work_monitor.scraper import RegisterClient, RegisterError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollResult:
    seen: int
    recorded: int
    notified: int
    failed: int


class Monitor:
    def __init__(self, settings: Settings, repository: OrderRepository, notifier: EmailNotifier) -> None:
        self._settings = settings
        self._repository = repository
        self._notifier = notifier

    def poll(self) -> PollResult:
        seen = 0
        recorded = 0
        failed = 0
        try:
            with RegisterClient(self._settings) as client:
                hits = client.iter_stop_work_orders()
                seen = len(hits)
                for hit in hits:
                    try:
                        fetched = client.fetch_order(hit)
                        parsed = build_parsed_order(fetched)
                    except (RegisterError, OSError, ValueError):
                        failed += 1
                        logger.exception("Could not read Stop Work Order %s", hit.source_path)
                        continue
                    if self._repository.save_new_order(parsed) is not None:
                        recorded += 1
        finally:
            notified = self._send_pending()
        result = PollResult(seen=seen, recorded=recorded, notified=notified, failed=failed)
        logger.info(
            "Poll finished: seen=%s recorded=%s notified=%s failed=%s",
            result.seen,
            result.recorded,
            result.notified,
            result.failed,
        )
        return result

    def _send_pending(self) -> int:
        if not self._settings.smtp.enabled:
            pending = self._repository.pending_notifications()
            if pending:
                logger.info(
                    "%s order(s) are waiting for notification because smtp.enabled is false",
                    len(pending),
                )
            return 0
        sent = 0
        for order in self._repository.pending_notifications():
            if self._notify(order):
                sent += 1
        return sent

    def _notify(self, order: StoredOrder) -> bool:
        try:
            self._notifier.send(order)
        except Exception as exc:
            logger.exception("Could not send notification for order %s", order.order_id)
            self._repository.mark_notified(order.order_id, str(exc)[:1000])
            return False
        self._repository.mark_notified(order.order_id, None)
        return True
