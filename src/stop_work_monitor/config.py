"""Load documented YAML settings and override secrets from the environment."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class SqlServerSettings(BaseModel):
    driver: str
    host: str
    port: int = Field(ge=1, le=65535)
    database: str
    username: str
    encrypt: bool = True
    trust_server_certificate: bool = False
    password: SecretStr


class SmtpSettings(BaseModel):
    enabled: bool = False
    host: str
    port: int = Field(ge=1, le=65535)
    username: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    from_address: str
    to_addresses: list[str]
    password: SecretStr = SecretStr("")

    @field_validator("to_addresses")
    @classmethod
    def strip_addresses(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def check_transport(self) -> SmtpSettings:
        if self.use_tls and self.use_ssl:
            raise ValueError("smtp.use_tls and smtp.use_ssl cannot both be true")
        if self.enabled and not self.to_addresses:
            raise ValueError("smtp.to_addresses must contain a recipient when email is enabled")
        if self.enabled and self.username and not self.password.get_secret_value():
            raise ValueError("SMTP_PASSWORD is required when smtp.username is set")
        return self


class Settings(BaseModel):
    poll_interval_minutes: int = Field(ge=1)
    register_search_url: str
    register_base_url: str
    agency_name: str
    order_category: str
    page_size: int = Field(ge=1, le=100)
    max_results: int = Field(ge=1)
    request_timeout_seconds: float = Field(gt=0)
    request_delay_seconds: float = Field(ge=0)
    max_pdf_bytes: int = Field(gt=0)
    user_agent: str
    timezone: str
    sqlserver: SqlServerSettings
    smtp: SmtpSettings


def _as_bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _apply_env(data: dict[str, object]) -> None:
    sqlserver = data.setdefault("sqlserver", {})
    smtp = data.setdefault("smtp", {})
    if not isinstance(sqlserver, dict) or not isinstance(smtp, dict):
        raise ValueError("sqlserver and smtp settings must be mappings")

    overrides = {
        "SQLSERVER_HOST": ("sqlserver", "host"),
        "SQLSERVER_PORT": ("sqlserver", "port"),
        "SQLSERVER_DATABASE": ("sqlserver", "database"),
        "SQLSERVER_DRIVER": ("sqlserver", "driver"),
        "SMTP_HOST": ("smtp", "host"),
        "SMTP_PORT": ("smtp", "port"),
        "SMTP_USERNAME": ("smtp", "username"),
        "SMTP_FROM": ("smtp", "from_address"),
    }
    sections = {"sqlserver": sqlserver, "smtp": smtp}
    for env_name, (section, key) in overrides.items():
        raw = os.environ.get(env_name)
        if raw:
            target = sections[section]
            target[key] = int(raw) if key == "port" else raw

    username = os.environ.get("SQLSERVER_USER")
    if not username:
        raise ValueError("SQLSERVER_USER is required and must not be stored in the YAML file")
    sqlserver["username"] = username
    
    password = os.environ.get("SQLSERVER_PASSWORD")
    if not password:
        raise ValueError("SQLSERVER_PASSWORD is required and must not be stored in the YAML file")
    sqlserver["password"] = password

    for env_name, key in (
        ("SQLSERVER_ENCRYPT", "encrypt"),
        ("SQLSERVER_TRUST_SERVER_CERTIFICATE", "trust_server_certificate"),
    ):
        raw = os.environ.get(env_name)
        if raw:
            sqlserver[key] = _as_bool(raw)

    smtp["password"] = os.environ.get("SMTP_PASSWORD", "")
    if os.environ.get("SMTP_ENABLED"):
        smtp["enabled"] = _as_bool(os.environ["SMTP_ENABLED"])
    if os.environ.get("SMTP_USE_TLS"):
        smtp["use_tls"] = _as_bool(os.environ["SMTP_USE_TLS"])
    if os.environ.get("SMTP_USE_SSL"):
        smtp["use_ssl"] = _as_bool(os.environ["SMTP_USE_SSL"])
    if os.environ.get("SMTP_TO"):
        smtp["to_addresses"] = os.environ["SMTP_TO"].split(",")
    if os.environ.get("POLL_INTERVAL_MINUTES"):
        data["poll_interval_minutes"] = int(os.environ["POLL_INTERVAL_MINUTES"])


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings.yaml, then apply environment overrides."""
    load_dotenv()
    settings_path = Path(path or os.environ.get("SETTINGS_FILE", "config/settings.yaml"))
    loaded = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{settings_path} must contain a mapping")
    _apply_env(loaded)
    settings = Settings.model_validate(loaded)
    _validate_database_name(settings.sqlserver.database)
    return settings


def _validate_database_name(name: str) -> None:
    if not name.isidentifier():
        raise ValueError("sqlserver.database must be a single SQL identifier")
