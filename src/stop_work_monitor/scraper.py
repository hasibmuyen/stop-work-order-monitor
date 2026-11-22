"""Read Stop Work Orders from the NSW register and their download PDFs."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from stop_work_monitor.config import Settings
from stop_work_monitor.domain import FetchedOrder, ListingHit
from stop_work_monitor.parsing import parse_listing_hit, publication_date

logger = logging.getLogger(__name__)


class RegisterError(Exception):
    """The register or an order PDF could not be read."""


class RegisterClient:
    """Client for the public register search used by the Building Commission page."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RegisterClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def iter_stop_work_orders(self) -> list[ListingHit]:
        hits: list[ListingHit] = []
        offset = 0
        total = self._settings.max_results
        while offset < min(total, self._settings.max_results):
            payload = self._search_body(offset)
            body = self._request("POST", self._settings.register_search_url, json=payload)
            data = body.json()
            page = data.get("hits", {}).get("hits", [])
            reported = data.get("hits", {}).get("total", 0)
            total = reported.get("value", 0) if isinstance(reported, dict) else int(reported)
            for item in page:
                source = item.get("_source", {})
                categories = source.get("name_category") or []
                if self._settings.order_category not in categories:
                    continue
                hit = parse_listing_hit(source)
                if hit.source_path:
                    hits.append(hit)
            if not page or len(page) < self._settings.page_size:
                break
            offset += len(page)
        logger.info("Register search returned %s Stop Work Order page(s)", len(hits))
        return hits

    def fetch_order(self, hit: ListingHit) -> FetchedOrder:
        source_url = urljoin(self._settings.register_base_url + "/", hit.source_path.lstrip("/"))
        page = self._request("GET", source_url)
        pdf_path = _pdf_href(page.text)
        pdf_url = urljoin(source_url, pdf_path) if pdf_path else None
        pdf_text = self._read_pdf(pdf_url) if pdf_url else None
        added_on = publication_date(
            hit.resource_timestamp,
            self._settings.timezone,
            datetime.now(ZoneInfo(self._settings.timezone)).date(),
        )
        return FetchedOrder(
            hit=hit,
            source_url=source_url,
            pdf_url=pdf_url,
            pdf_text=pdf_text,
            order_added_on=added_on,
        )

    def _search_body(self, offset: int) -> dict[str, object]:
        return {
            "_source": [
                "title",
                "url",
                "summary",
                "html_content",
                "resource_date",
                "name_category",
            ],
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"type": "resource"}},
                        {"terms": {"agency_name": [self._settings.agency_name]}},
                        {"terms": {"name_category": [self._settings.order_category]}},
                    ]
                }
            },
            # Oldest first, so the original order is stored before a later notice
            # that refers to the same site but does not repeat the licence number.
            "sort": [{"resource_date": "asc"}],
            "from": offset,
            "size": self._settings.page_size,
        }

    def _read_pdf(self, url: str) -> str:
        response = self._request("GET", url)
        content = response.content
        if len(content) > self._settings.max_pdf_bytes:
            raise RegisterError(f"PDF at {url} exceeds max_pdf_bytes")
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            reader.decrypt("")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if not text.strip():
            raise RegisterError(f"PDF at {url} has no extractable text")
        return text

    def _request(
        self,
        method: str,
        url: str,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.request(method, url, json=json)
                if response.status_code in {429, 500, 502, 503, 504}:
                    last_error = RegisterError(f"{method} {url} returned {response.status_code}")
                    time.sleep(2**attempt)
                    continue
                response.raise_for_status()
                if self._settings.request_delay_seconds and method == "GET":
                    time.sleep(self._settings.request_delay_seconds)
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise RegisterError(f"{method} {url} failed") from last_error


def _pdf_href(page_html: str) -> str | None:
    soup = BeautifulSoup(page_html, "html.parser")
    for anchor in soup.select("div.dcs-downloads a[href]"):
        href = str(anchor.get("href") or "")
        if href.split("?", 1)[0].lower().endswith(".pdf"):
            return href
    return None


