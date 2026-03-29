"""Pydantic model for scholarship scheme data."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SchemeModel(BaseModel):
    """Normalized scholarship scheme representation used across discovery."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = ""
    eligibility: str = ""
    source: str = ""
    source_type: str = "government"
    state: str = ""
    category: str = ""
    income_limit: int = 0
    course_level: str = ""
    provider: str = ""
    apply_link: str = ""
    match_score: int = 0
    match_reasons: list[str] = Field(default_factory=list)
    tinyfish_reason: str = ""
    tinyfish_priority: str = ""

    @field_validator("income_limit", "match_score", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @field_validator("match_reasons", mode="before")
    @classmethod
    def _coerce_match_reasons(cls, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source_type(cls, value: Any) -> str:
        lowered = str(value or "").strip().lower()
        if lowered == "private":
            return "private"
        return "government"

    @field_validator("tinyfish_priority", mode="before")
    @classmethod
    def _normalize_tinyfish_priority(cls, value: Any) -> str:
        return str(value or "").strip().lower()

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SchemeModel":
        if isinstance(d, cls):
            return d
        if not isinstance(d, dict):
            return cls()

        normalized = dict(d)
        aliases = {
            "scheme_name": "name",
            "schemeName": "name",
            "eligibilityText": "eligibility",
            "income": "income_limit",
            "type": "source_type",
        }

        for source_key, target_key in aliases.items():
            if source_key in normalized and not normalized.get(target_key):
                normalized[target_key] = normalized[source_key]

        if not normalized.get("source_type") and (
            str(normalized.get("type", "")).strip().lower() == "private" or normalized.get("provider")
        ):
            normalized["source_type"] = "private"

        return cls.model_validate(normalized)

    def to_display_line(self) -> str:
        line = f"{self.name} [{self.source}] (score: {self.match_score})"
        if self.tinyfish_priority:
            line += f" | Priority: {self.tinyfish_priority}"
        return line
