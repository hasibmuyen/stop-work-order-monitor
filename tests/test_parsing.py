from datetime import date

from stop_work_monitor.db import iter_sql_batches
from stop_work_monitor.domain import FetchedOrder, ListingHit
from stop_work_monitor.parsing import (
    build_parsed_order,
    company_name_from_title,
    company_number_type,
    dedup_key,
    extract_acn,
    extract_company_address,
    extract_license_number,
    extract_site_address,
    publication_date,
)

SUSTAINABLE = """
Builder: Sustainable Homes Australia R and D Pty Ltd
Lic. No: 367595C
Unit 6, 36 Abel Street
WALLSEND NSW 2287
Email to: sustainablehomesau@outlook.com
Stop Work Order
"""

AUSFIELD = """
Attn: Proper Officer CAS Ref:11472181
Ausfield Investment Pty Ltd
Lic. No. 361825C
10/6 Mount Olympus Blvd
Wolli Creek NSW 2205
Email: max@lcgroups.com.au
Stop Work Order
"""

NATOBY = """
ATTN: Proper Officer
Natoby Pty Ltd (A.C.N 601 533 519)
Level 3, 8 - 10 King Street
ROCKDALE, NSW, 2216
Via email:
Modified Stop Work Order
"""

JIANRONG = """
Attn. Jianrong Song
6 Devonshire Street
Chatswood NSW 2067
11 December 2025
Stop Work Order
"""

HERD = """
Attn: Proper Officer
Herd Street Developments Pty Ltd
ACN 647 350 187
12 Herd Street
Wollongong NSW 2500
Stop Work Order
"""


def test_company_name_is_taken_from_the_order_title() -> None:
    assert (
        company_name_from_title(
            "Stop Work Order for Ausfield Investment Pty Ltd at Unit 1 18 Roach St Arncliffe 2205"
        )
        == "Ausfield Investment Pty Ltd"
    )
    assert (
        company_name_from_title(
            "Notice of Imposition of a Condition Upon a Stop Work Order for "
            "Sustainable Homes Australia R And D Pty Ltd"
        )
        == "Sustainable Homes Australia R And D Pty Ltd"
    )
    assert company_name_from_title("Modified Stop Work Order for Natoby Pty Ltd") == "Natoby Pty Ltd"
    assert company_name_from_title("Stop Work Order for Jianrong Song") == "Jianrong Song"


def test_licence_number_is_read_from_pdf_letterhead() -> None:
    assert extract_license_number(SUSTAINABLE) == "367595C"
    assert extract_license_number(AUSFIELD) == "361825C"
    assert extract_license_number(NATOBY) is None
    assert extract_license_number(JIANRONG) is None


def test_acn_is_normalised_to_nine_digits() -> None:
    assert extract_acn(NATOBY) == "601533519"
    assert extract_acn(HERD) == "647350187"
    assert extract_acn(SUSTAINABLE) is None
    assert extract_acn(JIANRONG) is None


def test_company_number_type_prefers_licence_then_acn() -> None:
    assert company_number_type("367595C", "601533519") == "licence"
    assert company_number_type(None, "601533519") == "acn"
    assert company_number_type(None, None) == "unstated"


def test_company_address_is_the_letterhead_not_the_work_site() -> None:
    assert extract_company_address(SUSTAINABLE) == "Unit 6, 36 Abel Street WALLSEND NSW 2287"
    assert extract_company_address(AUSFIELD) == "10/6 Mount Olympus Blvd Wolli Creek NSW 2205"
    assert extract_company_address(NATOBY) == "Level 3, 8 - 10 King Street ROCKDALE, NSW, 2216"
    assert extract_company_address(JIANRONG) == "6 Devonshire Street Chatswood NSW 2067"


def test_same_licence_at_different_sites_is_not_treated_as_a_duplicate() -> None:
    first = dedup_key("361825C", "licence", "Unit 1, 18 Roach Street", "https://example.test/one")
    second = dedup_key("361825C", "licence", "137 Bayview Avenue", "https://example.test/two")
    repeat = dedup_key("361825c", "licence", "unit 1,  18 roach street", "https://example.test/other")
    assert first != second
    assert first == repeat


def test_same_acn_at_the_same_site_is_one_order() -> None:
    first = dedup_key("601533519", "acn", "8 King Street", "https://example.test/a")
    repeat = dedup_key("601533519", "acn", "8 king street", "https://example.test/b")
    other_site = dedup_key("601533519", "acn", "12 Herd Street", "https://example.test/c")
    assert first == repeat
    assert first != other_site


def test_order_without_a_company_number_is_identified_by_its_url() -> None:
    assert dedup_key(None, "unstated", "2 Waruda Street", "https://example.test/a") != dedup_key(
        None, "unstated", "2 Waruda Street", "https://example.test/b"
    )


def test_site_address_prefers_the_register_summary() -> None:
    summary = "71 Terrigal Drive, Terrigal, NSW, 2260 (Lot 24 DP 511006)"
    html = "<p>located at somewhere else (the Development).</p>"
    assert extract_site_address(summary, html) == summary
    assert extract_site_address("", html) == "somewhere else"


def test_publication_timestamp_uses_the_configured_timezone() -> None:
    # 1784894400 is 24 July 2026 12:00 in Australia/Sydney.
    assert publication_date(1784894400, "Australia/Sydney", date(2000, 1, 1)) == date(2026, 7, 24)


def test_parsed_order_keeps_company_number_and_both_addresses() -> None:
    fetched = FetchedOrder(
        hit=ListingHit(
            title="Stop Work Order for Sustainable Homes Australia R and D Pty Ltd",
            source_path="/orders/sustainable",
            summary="71 Terrigal Drive, Terrigal, NSW, 2260",
            html_content="",
            resource_timestamp=1784894400,
        ),
        source_url="https://www.nsw.gov.au/orders/sustainable",
        pdf_url="https://www.nsw.gov.au/files/order.pdf",
        pdf_text=SUSTAINABLE,
        order_added_on=date(2026, 7, 24),
    )
    parsed = build_parsed_order(fetched)
    assert parsed.company_number == "367595C"
    assert parsed.company_number_type == "licence"
    assert parsed.company_name == "Sustainable Homes Australia R and D Pty Ltd"
    assert parsed.company_address == "Unit 6, 36 Abel Street WALLSEND NSW 2287"
    assert parsed.site_address == "71 Terrigal Drive, Terrigal, NSW, 2260"
    assert parsed.order_added_on == date(2026, 7, 24)


def test_parsed_order_records_acn_as_the_company_number_when_no_licence_is_printed() -> None:
    fetched = FetchedOrder(
        hit=ListingHit(
            title="Modified Stop Work Order for Natoby Pty Ltd",
            source_path="/orders/natoby",
            summary="8-10 King Street, Rockdale NSW 2216",
            html_content="",
            resource_timestamp=None,
        ),
        source_url="https://www.nsw.gov.au/orders/natoby",
        pdf_url="https://www.nsw.gov.au/files/natoby.pdf",
        pdf_text=NATOBY,
        order_added_on=date(2026, 3, 1),
    )
    parsed = build_parsed_order(fetched)
    assert parsed.company_number == "601533519"
    assert parsed.company_number_type == "acn"
    assert parsed.company_name == "Natoby Pty Ltd"


def test_schema_script_creates_the_required_columns() -> None:
    script = open("scripts/init_db.sql", encoding="utf-8").read()
    batches = iter_sql_batches(script)
    assert any("CREATE DATABASE" in batch for batch in batches)
    company_table = script.split("CREATE TABLE dbo.companies", 1)[1].split("\n    );", 1)[0]
    order_table = script.split("CREATE TABLE dbo.stop_work_orders", 1)[1].split("\n    );", 1)[0]
    assert "company_number NVARCHAR(50) NULL" in company_table
    assert "company_number" not in order_table
    assert "company_number_type" not in order_table
    assert "license_number NVARCHAR" not in company_table
    assert "license_number NVARCHAR" not in order_table
    assert "DROP COLUMN company_number" in script
    assert "DROP COLUMN company_number_type" in script
    assert "company_number_type" in script
    assert "ck_companies_number_type" in script
    assert "company_address" in script
    assert "liquidation_list_added_on" in script
    assert "site_address" in script
    assert "order_added_on" in script
    assert "uq_stop_work_orders_dedup_key" in script
