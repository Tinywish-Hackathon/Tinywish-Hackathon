"""Pydantic model for scholarship scheme data."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DEADLINE_PATTERNS = [
    (re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"), ("%Y-%m-%d",)),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"), ("%d/%m/%Y", "%m/%d/%Y")),
    (re.compile(r"\b\d{1,2}-\d{1,2}-\d{4}\b"), ("%d-%m-%Y", "%m-%d-%Y")),
    (re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"), ("%d %B %Y", "%d %b %Y")),
    (
        re.compile(r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b"),
        ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"),
    ),
]


def _parse_deadline_candidate(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    text = str(value).strip()
    if not text:
        return None

    for pattern, formats in _DEADLINE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        raw_value = match.group(0).strip()
        normalized_value = re.sub(r"\s+", " ", raw_value).strip()
        for fmt in formats:
            try:
                return datetime.strptime(normalized_value, fmt)
            except ValueError:
                continue

    return None


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
    deadline: datetime | None = None
    deadline_text: str = ""
    status: str = ""
    match_score: int = 0
    match_reasons: list[str] = Field(default_factory=list)
    tinyfish_reason: str = ""
    tinyfish_priority: str = ""
    applyability_score: int = 0
    is_applyable: bool = False
    is_expired: bool = False
    days_left: int | None = None
    urgency: str = "UNKNOWN"

    @field_validator("income_limit", "match_score", "applyability_score", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @field_validator("days_left", mode="before")
    @classmethod
    def _coerce_optional_int(cls, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @model_validator(mode="before")
    @classmethod
    def _hydrate_deadline_text(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        deadline_value = normalized.get("deadline")
        if deadline_value not in (None, "") and not normalized.get("deadline_text"):
            if isinstance(deadline_value, (datetime, date)):
                normalized["deadline_text"] = deadline_value.strftime("%Y-%m-%d")
            else:
                normalized["deadline_text"] = str(deadline_value)

        return normalized

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

    @field_validator("deadline", mode="before")
    @classmethod
    def _normalize_deadline(cls, value: Any) -> datetime | None:
        return _parse_deadline_candidate(value)

    @field_validator("deadline_text", mode="before")
    @classmethod
    def _normalize_deadline_text(cls, value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, (datetime, date)):
            return value.strftime("%Y-%m-%d")
        return str(value).strip()

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> str:
        lowered = str(value or "").strip().lower()
        if any(keyword in lowered for keyword in ("closed", "expired", "deadline over", "application over")):
            return "closed"
        if lowered == "open":
            return "open"
        return "open"

    @field_validator("urgency", mode="before")
    @classmethod
    def _normalize_urgency(cls, value: Any) -> str:
        normalized = str(value or "").strip().upper()
        if normalized in {"HIGH", "MEDIUM", "LOW"}:
            return normalized
        return "UNKNOWN"

    @field_validator("tinyfish_priority", mode="before")
    @classmethod
    def _normalize_tinyfish_priority(cls, value: Any) -> str:
        return str(value or "").strip().lower()

    @field_validator("is_expired", mode="before")
    @classmethod
    def _normalize_is_expired(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "closed", "expired"}

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
            "deadlineText": "deadline",
            "deadline_text": "deadline",
            "last_date": "deadline",
            "lastDate": "deadline",
            "closing_date": "deadline",
            "closingDate": "deadline",
            "end_date": "deadline",
            "endDate": "deadline",
            "deadline_status": "status",
            "deadlineStatus": "status",
            "application_status": "status",
        }

        for source_key, target_key in aliases.items():
            if source_key in normalized and not normalized.get(target_key):
                normalized[target_key] = normalized[source_key]

        if normalized.get("deadline") not in (None, "") and not normalized.get("deadline_text"):
            normalized["deadline_text"] = str(normalized["deadline"])

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
