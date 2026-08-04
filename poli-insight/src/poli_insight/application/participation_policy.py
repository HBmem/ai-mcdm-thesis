"""Shared interpretation of immutable participant-facing configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.session import SessionConfigurationVersion


@dataclass(frozen=True, slots=True)
class ConsentPolicy:
    required: bool
    version: str
    title: str
    statement: str

    @property
    def statement_hash(self) -> str:
        return hash_json(
            {"version": self.version, "title": self.title, "statement": self.statement}
        )


def consent_policy(configuration: SessionConfigurationVersion) -> ConsentPolicy:
    raw = configuration.configuration_json.get("consent")
    if not isinstance(raw, Mapping):
        return ConsentPolicy(False, "none", "Research consent", "")
    required = raw.get("required") is True
    version = _text(raw.get("version"), "1")
    title = _text(raw.get("title"), "Research participation consent")
    statement = _text(raw.get("statement"), "")
    if required and not statement:
        raise ValueError("Required consent configuration has no statement.")
    return ConsentPolicy(required, version, title, statement)


def _text(value: Any, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default
