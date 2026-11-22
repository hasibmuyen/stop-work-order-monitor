"""Values passed between the register client, parser, and database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ListingHit:
    """One Stop Work Order returned by the register search."""

    title: str
    source_path: str
    summary: str
    html_content: str
    resource_timestamp: int | None


@dataclass(frozen=True)
class FetchedOrder:
    """A listing hit plus the PDF linked under Resource downloads."""

    hit: ListingHit
    source_url: str
    pdf_url: str | None
    pdf_text: str | None
    order_added_on: date


@dataclass(frozen=True)
class ParsedOrder:
    """Order ready to store. Identity is the company number and site address."""

    company_name: str
    company_address: str | None
    company_number: str | None
    company_number_type: str
    site_address: str
    order_title: str
    source_url: str
    pdf_url: str | None
    order_added_on: date
    company_key: str
    dedup_key: str
    source_url_hash: str
    site_key: str


@dataclass(frozen=True)
class StoredOrder:
    """Row that still needs an email, or a row just inserted."""

    order_id: int
    company_name: str
    company_number: str | None
    company_number_type: str
    order_added_on: date
    site_address: str
    source_url: str
