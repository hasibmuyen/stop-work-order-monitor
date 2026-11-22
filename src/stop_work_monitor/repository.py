"""Store companies and Stop Work Orders without duplicating an order."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from stop_work_monitor.domain import ParsedOrder, StoredOrder

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class CompanyRow(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_key: Mapped[str] = mapped_column(String(64))
    company_number: Mapped[str | None] = mapped_column(String(50))
    company_number_type: Mapped[str] = mapped_column(String(20))
    company_name: Mapped[str] = mapped_column(String(300))
    company_address: Mapped[str | None] = mapped_column(String(500))
    liquidation_list_added_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class StopWorkOrderRow(Base):
    __tablename__ = "stop_work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    site_address: Mapped[str] = mapped_column(String(500))
    order_title: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str] = mapped_column(String(1000))
    source_url_hash: Mapped[str] = mapped_column(String(64))
    dedup_key: Mapped[str] = mapped_column(String(64))
    site_key: Mapped[str] = mapped_column(String(64))
    pdf_url: Mapped[str | None] = mapped_column(String(1000))
    order_added_on: Mapped[date] = mapped_column(Date)
    notification_sent: Mapped[bool] = mapped_column(Boolean)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    notification_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class OrderRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_new_order(self, order: ParsedOrder) -> StoredOrder | None:
        """Insert an unseen order. Return None when the licence and site are already stored."""
        with Session(self._engine) as session:
            existing = self._find_existing(session, order)
            if existing is not None:
                _enrich_existing(session, existing, order)
                session.commit()
                return None
            company = session.scalar(select(CompanyRow).where(CompanyRow.company_key == order.company_key))
            if company is None:
                company = CompanyRow(
                    company_key=order.company_key,
                    company_number=order.company_number,
                    company_number_type=order.company_number_type,
                    company_name=order.company_name[:300],
                    company_address=_clip(order.company_address, 500),
                    liquidation_list_added_on=order.order_added_on,
                    created_at=_utc_now(),
                )
                session.add(company)
                session.flush()
            else:
                _refresh_company(company, order)
            row = StopWorkOrderRow(
                company_id=company.id,
                site_address=order.site_address[:500],
                order_title=order.order_title[:500],
                source_url=order.source_url[:1000],
                source_url_hash=order.source_url_hash,
                dedup_key=order.dedup_key,
                site_key=order.site_key,
                pdf_url=_clip(order.pdf_url, 1000),
                order_added_on=order.order_added_on,
                notification_sent=False,
                notification_sent_at=None,
                notification_error=None,
                created_at=_utc_now(),
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                logger.info("Order already stored for %s", order.source_url)
                return None
            logger.info(
                "Recorded Stop Work Order for %s (%s) at %s",
                order.company_name,
                order.company_number or "no company number stated",
                order.site_address,
            )
            return StoredOrder(
                order_id=row.id,
                company_name=company.company_name,
                company_number=company.company_number,
                company_number_type=company.company_number_type,
                order_added_on=order.order_added_on,
                site_address=order.site_address,
                source_url=order.source_url,
            )

    def pending_notifications(self) -> list[StoredOrder]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(
                    StopWorkOrderRow,
                    CompanyRow.company_name,
                    CompanyRow.company_number,
                    CompanyRow.company_number_type,
                )
                .join(CompanyRow, CompanyRow.id == StopWorkOrderRow.company_id)
                # .is_(False) renders as "IS 0", which SQL Server rejects.
                .where(StopWorkOrderRow.notification_sent == False)  # noqa: E712
                .order_by(StopWorkOrderRow.id)
            ).all()
            return [
                StoredOrder(
                    order_id=order.id,
                    company_name=company_name,
                    company_number=company_number,
                    company_number_type=company_number_type,
                    order_added_on=order.order_added_on,
                    site_address=order.site_address,
                    source_url=order.source_url,
                )
                for order, company_name, company_number, company_number_type in rows
            ]

    def mark_notified(self, order_id: int, error: str | None) -> None:
        sent = error is None
        with Session(self._engine) as session:
            session.execute(
                update(StopWorkOrderRow)
                .where(StopWorkOrderRow.id == order_id)
                .values(
                    notification_sent=sent,
                    notification_sent_at=_utc_now() if sent else None,
                    notification_error=_clip(error, 1000),
                )
            )
            session.commit()

    def _find_existing(self, session: Session, order: ParsedOrder) -> StopWorkOrderRow | None:
        return session.scalar(
            select(StopWorkOrderRow).where(
                (StopWorkOrderRow.source_url_hash == order.source_url_hash)
                | (StopWorkOrderRow.dedup_key == order.dedup_key)
                | (StopWorkOrderRow.site_key == order.site_key)
            )
        )


def _enrich_existing(session: Session, existing: StopWorkOrderRow, order: ParsedOrder) -> None:
    """Fill a missing company number without treating a later notice as new."""
    company = session.get(CompanyRow, existing.company_id)
    if company is None:
        return
    if order.company_number and not company.company_number:
        company = _claim_company_number(session, company, order)
    _refresh_company(company, order)


def _claim_company_number(
    session: Session,
    company: CompanyRow,
    order: ParsedOrder,
) -> CompanyRow:
    other = session.scalar(select(CompanyRow).where(CompanyRow.company_key == order.company_key))
    if other is not None and other.id != company.id:
        return other
    company.company_number = order.company_number
    company.company_number_type = order.company_number_type
    company.company_key = order.company_key
    return company


def _refresh_company(company: CompanyRow, order: ParsedOrder) -> None:
    if order.order_added_on < company.liquidation_list_added_on:
        company.liquidation_list_added_on = order.order_added_on
    if order.company_address and not company.company_address:
        company.company_address = order.company_address[:500]
    if order.company_number and not company.company_number:
        company.company_number = order.company_number
        company.company_number_type = order.company_number_type


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value[:limit]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
