"""Run one poll, or keep polling on the configured interval."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from stop_work_monitor.config import load_settings
from stop_work_monitor.db import apply_schema, create_app_engine
from stop_work_monitor.monitor import Monitor
from stop_work_monitor.notifier import EmailNotifier
from stop_work_monitor.repository import OrderRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Monitor NSW Stop Work Orders and record new orders in SQL Server."
    )
    parser.add_argument("--once", action="store_true", help="Poll once and exit.")
    parser.add_argument("--settings", help="Path to the YAML configuration file.")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings(args.settings)
    engine = create_app_engine(settings)
    apply_schema(engine)
    monitor = Monitor(settings, OrderRepository(engine), EmailNotifier(settings.smtp))
    if args.once:
        monitor.poll()
        engine.dispose()
        return 0

    scheduler = BlockingScheduler()
    scheduler.add_job(
        monitor.poll,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        next_run_time=datetime.now(),
    )
    logging.getLogger(__name__).info(
        "Polling every %s minute(s). Press Ctrl+C to stop.",
        settings.poll_interval_minutes,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
