"""
Configuration validation models using Pydantic.

Ensures that config.yaml is validated at startup, preventing downstream
KeyError or TypeError failures during a scrape run.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from pipeline.schema import Category


class PathsConfig(BaseModel):
    fingerprint_store: str = "storage/fingerprints.json"
    runs_dir: str = "runs"
    cache_dir: str = ".cache"
    backend_catalog_dir: str = "auctionnow_backend_json"


class HttpConfig(BaseModel):
    user_agent: str
    default_timeout_seconds: float = Field(default=15.0, ge=1.0)
    default_rate_limit_seconds: float = Field(default=3.0, ge=0.0)
    cache_max_age_hours: float = Field(default=72.0, ge=0.0)

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, v: str) -> str:
        if not v or len(v.strip()) < 5:
            raise ValueError("user_agent must be non-empty and descriptive")
        return v.strip()


class SourceConfig(BaseModel):
    id: str
    category: Category
    name: str
    base_url: str
    enabled: bool = False
    rate_limit_seconds: float = Field(default=3.0, ge=0.0)
    notes: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/")


class NotificationsConfig(BaseModel):
    slack_webhook_url: str | None = ""


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    http: HttpConfig
    sources: list[SourceConfig] = Field(default_factory=list)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)


def load_and_validate_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """
    Load and strictly validate config.yaml.
    Raises FileNotFoundError if file is missing, or pydantic.ValidationError if invalid.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path.resolve()}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise TypeError(f"Configuration in {path} must be a valid YAML mapping")

    return AppConfig.model_validate(raw)
