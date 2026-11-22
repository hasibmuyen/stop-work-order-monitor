from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from stop_work_monitor.domain import ParsedOrder
from stop_work_monitor.parsing import company_key, dedup_key, sha256_text, site_key
from stop_work_monitor.repository import (
    CompanyRow,
    OrderRepository,
    StopWorkOrderRow,
)


@pytest.fixture
def repository_engine() -> Engine:
    engine = create_engine("sqlite://")
    StopWorkOrderRow.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _order(
    *,
    source_url: str = "https://example.test/orders/1",
    company_name: str = "Example Pty Ltd",
    company_number: str | None = "367595C",
    company_number_type: str = "licence",
    company_address: str | None = "1 Registered Street, Sydney NSW 2000",
    site_address: str = "10 Building Street, Sydney NSW 2000",
    order_added_on: date = date(2026, 1, 10),
) -> ParsedOrder:
    return ParsedOrder(
        company_name=company_name,
        company_address=company_address,
        company_number=company_number,
        company_number_type=company_number_type,
        site_address=site_address,
        order_title=f"Stop Work Order for {company_name}",
        source_url=source_url,
        source_nid=None,
        pdf_url=f"{source_url}.pdf",
        order_added_on=order_added_on,
        company_key=company_key(company_number, company_number_type, company_name),
        dedup_key=dedup_key(
            company_number,
            company_number_type,
            site_address,
            source_url,
        ),
        source_url_hash=sha256_text(source_url),
        site_key=site_key(company_name, site_address, source_url),
    )


def test_save_new_order_persists_company_and_order(repository_engine: Engine) -> None:
    repository = OrderRepository(repository_engine)
    saved = repository.save_new_order(_order())

    assert saved is not None
    assert saved.order_id == 1
    assert saved.company_name == "Example Pty Ltd"
    assert saved.company_number == "367595C"
    assert saved.company_number_type == "licence"

    with Session(repository_engine) as session:
        company = session.scalar(select(CompanyRow))
        order = session.scalar(select(StopWorkOrderRow))

    assert company is not None
    assert company.company_number == "367595C"
    assert company.company_number_type == "licence"
    assert company.company_address == "1 Registered Street, Sydney NSW 2000"
    assert company.liquidation_list_added_on == date(2026, 1, 10)
    assert order is not None
    assert order.company_id == company.id
    assert order.notification_sent is False
    assert order.order_added_on == date(2026, 1, 10)
    assert "company_number" not in StopWorkOrderRow.__table__.columns
    assert "company_number_type" not in StopWorkOrderRow.__table__.columns


def test_save_duplicate_order_does_not_add_another_row(repository_engine: Engine) -> None:
    repository = OrderRepository(repository_engine)
    assert repository.save_new_order(_order()) is not None
    assert repository.save_new_order(_order()) is None

    with Session(repository_engine) as session:
        assert session.scalar(select(func.count()).select_from(CompanyRow)) == 1
        assert session.scalar(select(func.count()).select_from(StopWorkOrderRow)) == 1


def test_same_company_can_have_orders_at_different_sites(repository_engine: Engine) -> None:
    repository = OrderRepository(repository_engine)
    assert repository.save_new_order(_order()) is not None
    second_site = _order(
        source_url="https://example.test/orders/2",
        site_address="20 Another Street, Sydney NSW 2000",
        order_added_on=date(2026, 1, 5),
    )
    assert repository.save_new_order(second_site) is not None

    with Session(repository_engine) as session:
        assert session.scalar(select(func.count()).select_from(CompanyRow)) == 1
        assert session.scalar(select(func.count()).select_from(StopWorkOrderRow)) == 2
        company = session.scalar(select(CompanyRow))

    assert company is not None
    assert company.liquidation_list_added_on == date(2026, 1, 5)


def test_pending_notifications_include_unsent_orders_and_mark_sent(
    repository_engine: Engine,
) -> None:
    repository = OrderRepository(repository_engine)
    saved = repository.save_new_order(_order())
    assert saved is not None

    assert repository.pending_notifications() == [saved]
    repository.mark_notified(saved.order_id, None)

    assert repository.pending_notifications() == []
    with Session(repository_engine) as session:
        order = session.get(StopWorkOrderRow, saved.order_id)
    assert order is not None
    assert order.notification_sent is True
    assert order.notification_sent_at is not None
    assert order.notification_error is None


def test_failed_notification_remains_pending_with_error(repository_engine: Engine) -> None:
    repository = OrderRepository(repository_engine)
    saved = repository.save_new_order(_order())
    assert saved is not None
    repository.mark_notified(saved.order_id, "SMTP unavailable")

    assert repository.pending_notifications() == [saved]
    with Session(repository_engine) as session:
        order = session.get(StopWorkOrderRow, saved.order_id)
    assert order is not None
    assert order.notification_sent is False
    assert order.notification_sent_at is None
    assert order.notification_error == "SMTP unavailable"


def test_existing_order_is_enriched_with_later_company_number(
    repository_engine: Engine,
) -> None:
    repository = OrderRepository(repository_engine)
    original = _order(
        source_url="https://example.test/orders/original",
        company_number=None,
        company_number_type="unstated",
    )
    assert repository.save_new_order(original) is not None

    later_notice = _order(
        source_url="https://example.test/orders/later",
        company_number="601533519",
        company_number_type="acn",
        order_added_on=date(2026, 1, 12),
    )
    assert repository.save_new_order(later_notice) is None

    with Session(repository_engine) as session:
        companies = session.scalars(select(CompanyRow)).all()
        orders = session.scalars(select(StopWorkOrderRow)).all()

    assert len(companies) == 1
    assert len(orders) == 1
    assert companies[0].company_number == "601533519"
    assert companies[0].company_number_type == "acn"
    assert not hasattr(orders[0], "company_number")
    assert not hasattr(orders[0], "company_number_type")
    pending = repository.pending_notifications()
    assert len(pending) == 1
    assert pending[0].company_number == "601533519"
    assert pending[0].company_number_type == "acn"
