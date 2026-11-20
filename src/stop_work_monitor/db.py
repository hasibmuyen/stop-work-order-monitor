"""Connect to SQL Server and apply scripts/init_db.sql."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from stop_work_monitor.config import Settings, SqlServerSettings

logger = logging.getLogger(__name__)

_CREATE_OR_USE = re.compile(r"(?is)^(if\s+db_id|use)\b")


def schema_path() -> Path:
    configured = Path("scripts/init_db.sql")
    if configured.is_file():
        return configured
    packaged = Path(__file__).resolve().parents[2] / "scripts" / "init_db.sql"
    return packaged


def iter_sql_batches(script: str) -> list[str]:
    batches: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        if line.strip().upper() == "GO":
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    tail = "\n".join(current).strip()
    if tail:
        batches.append(tail)
    return batches


def odbc_connection_string(settings: SqlServerSettings, database: str) -> str:
    """Build the ODBC string, including the login password as PWD."""
    encrypt = "yes" if settings.encrypt else "no"
    trust = "yes" if settings.trust_server_certificate else "no"
    server = settings.host
    if not server.casefold().startswith("(localdb)") and settings.port:
        server = f"{server},{settings.port}"
    return (
        f"DRIVER={{{settings.driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={_odbc_value(settings.username)};"
        f"PWD={_odbc_value(settings.password.get_secret_value())};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust};"
        "MARS_Connection=no;"
        "APP=stop-work-order-monitor;"
    )


def connection_url(settings: SqlServerSettings, database: str) -> str:
    return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_connection_string(settings, database))}"


def create_app_engine(settings: Settings, attempts: int = 12, delay_seconds: float = 5) -> Engine:
    """Create the configured database if needed, then return an engine for it."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _ensure_database(settings)
            engine = create_engine(connection_url(settings.sqlserver, settings.sqlserver.database), future=True)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return engine
        except Exception as exc:
            last_error = exc
            logger.warning(
                "SQL Server is not ready (attempt %s of %s): %s",
                attempt,
                attempts,
                exc.__class__.__name__,
            )
            time.sleep(delay_seconds)
    raise RuntimeError("Could not connect to SQL Server") from last_error


def apply_schema(engine: Engine) -> None:
    script = (schema_path()).read_text(encoding="utf-8")
    with engine.connect() as connection:
        for batch in iter_sql_batches(script):
            if _CREATE_OR_USE.match(batch):
                continue
            connection.execute(text(batch))
        connection.commit()
    logger.info("Database schema is ready")


def _odbc_value(value: str) -> str:
    if any(character in value for character in (";", "{", "}", "=")):
        return "{" + value.replace("}", "}}") + "}"
    return value

def _ensure_database(settings: Settings) -> None:
    name = settings.sqlserver.database
    try:
        _create_database(connection_url(settings.sqlserver, "master"), name)
    except ProgrammingError as exc:
        if "permission denied" not in str(exc).casefold():
            raise
        logger.info(
            "SQL login cannot create databases; creating %s with Windows authentication",
            name,
        )

def _create_database(url: str, name: str) -> None:
    engine = create_engine(url, future=True)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(
                text(f"IF DB_ID(N'{name}') IS NULL BEGIN CREATE DATABASE [{name}]; END")
            )
    finally:
        engine.dispose()
