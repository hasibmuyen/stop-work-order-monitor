"""Extract company, licence, and address details from register text."""

from __future__ import annotations

import hashlib
import html
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from stop_work_monitor.domain import FetchedOrder, ListingHit, ParsedOrder

_TITLE_COMPANY = re.compile(
    r"(?i)^(?:notice of imposition of a condition upon a |modified )?"
    r"stop work order for (.+?)(?: at .+)?$"
)
_LICENSE = re.compile(
    r"(?i)\blic(?:en[cs]e|\.)?\s*(?:no\.?|number)\s*[:.]?\s*"
    r"([A-Z0-9][A-Z0-9-]{2,20})\b"
)
_ACN = re.compile(r"(?i)\bA\s*\.?\s*C\s*\.?\s*N\s*\.?\s*[:.]?\s*(\d[\d\s]{7,16})")
LICENCE = "licence"
ACN = "acn"
UNSTATED = "unstated"
_SITE_ADDRESS = re.compile(
    r"(?is)located at\s+(.+?)(?:\s*\(the development\)|\.(?:\s|$)|</p>)"
)
_POSTCODE_LINE = re.compile(r"(?i)\b(?:NSW|New South Wales)\b.{0,20}\b\d{4}\b")
_DATE_LINE = re.compile(
    r"^\d{1,2}(?:/|-)\d{1,2}(?:/|-)\d{4}$|^\d{1,2}\s+[A-Za-z]+\s+\d{4}$"
)
_STOP_ADDRESS = re.compile(
    r"(?i)^(email\b|via email\b|stop work order\b|section \d|cas ref\b|"
    r"attn\b|building commission\b)"
)
_COMPANY_LINE = re.compile(r"(?i)\b(pty|ltd|limited|a\.?c\.?n)\b")


def first_text(value: object) -> str:
    """Return the first string from an Elasticsearch scalar-or-list field."""
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    if value is None:
        return ""
    return str(value).strip()


def first_int(value: object) -> int | None:
    text = first_text(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_listing_hit(source: dict[str, object]) -> ListingHit:
    return ListingHit(
        title=html.unescape(first_text(source.get("title"))),
        source_path=first_text(source.get("url")),
        summary=html.unescape(first_text(source.get("summary"))),
        html_content=first_text(source.get("html_content")),
        resource_timestamp=first_int(source.get("resource_date")),
        source_nid=first_int(source.get("nid")),
    )


def publication_date(timestamp: int | None, timezone_name: str, fallback: date) -> date:
    """Convert a register Unix timestamp into a local calendar date."""
    if timestamp is None:
        return fallback
    moment = datetime.fromtimestamp(timestamp, ZoneInfo(timezone_name))
    return moment.date()


def company_name_from_title(title: str) -> str:
    match = _TITLE_COMPANY.match(re.sub(r"\s+", " ", title).strip())
    if not match:
        return title.strip()
    return re.sub(r"\s+", " ", match.group(1)).strip(" .")


def extract_license_number(pdf_text: str) -> str | None:
    match = _LICENSE.search(pdf_text or "")
    if not match:
        return None
    return match.group(1).upper()


def extract_acn(pdf_text: str) -> str | None:
    """Return the 9-digit ACN, ignoring spaces in forms such as 'A.C.N 601 533 519'."""
    match = _ACN.search(pdf_text or "")
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    if len(digits) < 9:
        return None
    return digits[:9]


def company_number_type(license_number: str | None, acn: str | None) -> str:
    """Licence identifies the company when both numbers are printed."""
    if license_number:
        return LICENCE
    if acn:
        return ACN
    return UNSTATED


def extract_site_address(summary: str, html_content: str) -> str:
    if summary.strip():
        return re.sub(r"\s+", " ", summary).strip()
    match = _SITE_ADDRESS.search(html_content or "")
    if match:
        return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip(" .")
    return ""


def extract_company_address(pdf_text: str) -> str | None:
    """Read the registered address from the letterhead, not the work site."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in (pdf_text or "").splitlines()]
    lines = [line for line in lines if line]
    start = _address_start(lines)
    if start is None:
        return None
    collected: list[str] = []
    for line in lines[start : start + 6]:
        if _STOP_ADDRESS.match(line) or _DATE_LINE.match(line):
            break
        if not collected and _COMPANY_LINE.search(line):
            continue
        collected.append(line)
        if _POSTCODE_LINE.search(line):
            break
    address = " ".join(collected).strip(" ,")
    return address or None


def _address_start(lines: list[str]) -> int | None:
    for index, line in enumerate(lines[:40]):
        if _LICENSE.search(line):
            return index + 1
    for index, line in enumerate(lines[:40]):
        if re.match(r"(?i)^attn\b", line):
            return index + 1
    return None


def normalize_address(value: str) -> str:
    """Compare addresses without punctuation or NSW wording differences."""
    text = value.casefold().replace("new south wales", "nsw")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def company_key(
    company_number: str | None,
    number_type: str,
    company_name: str,
) -> str:
    if company_number and number_type == LICENCE:
        identity = f"licence|{company_number.casefold()}"
    elif company_number and number_type == ACN:
        identity = f"acn|{company_number}"
    else:
        identity = f"name|{normalize_address(company_name)}"
    return sha256_text(identity)


def site_key(company_name: str, site_address: str, source_url: str) -> str:
    """Same company and site is one order, even when a later notice has no licence."""
    if not site_address or site_address == "Address not stated":
        return sha256_text(f"url|{source_url}")
    return sha256_text(f"site|{normalize_address(company_name)}|{normalize_address(site_address)}")


def dedup_key(
    company_number: str | None,
    number_type: str,
    site_address: str,
    source_url: str,
) -> str:
    """Identify an order by its typed company number and site.

    A company can have one order for each site. A page with neither number is
    identified by its register URL so the same page is not stored twice.
    """
    if company_number and number_type == LICENCE and site_address:
        identity = f"licence|{company_number.casefold()}|{normalize_address(site_address)}"
    elif company_number and number_type == ACN and site_address:
        identity = f"acn|{company_number}|{normalize_address(site_address)}"
    else:
        identity = f"url|{source_url}"
    return sha256_text(identity)


def build_parsed_order(fetched: FetchedOrder) -> ParsedOrder:
    pdf_text = fetched.pdf_text or ""
    license_number = extract_license_number(pdf_text)
    acn = extract_acn(pdf_text)
    number_type = company_number_type(license_number, acn)
    company_number = license_number or acn
    site_address = extract_site_address(fetched.hit.summary, fetched.hit.html_content)
    if not site_address:
        site_address = "Address not stated"
    company_name = company_name_from_title(fetched.hit.title)
    return ParsedOrder(
        company_name=company_name,
        company_address=extract_company_address(pdf_text),
        company_number=company_number,
        company_number_type=number_type,
        site_address=site_address,
        order_title=fetched.hit.title,
        source_url=fetched.source_url,
        source_nid=fetched.hit.source_nid,
        pdf_url=fetched.pdf_url,
        order_added_on=fetched.order_added_on,
        company_key=company_key(company_number, number_type, company_name),
        dedup_key=dedup_key(company_number, number_type, site_address, fetched.source_url),
        source_url_hash=sha256_text(fetched.source_url),
        site_key=site_key(company_name, site_address, fetched.source_url),
    )
