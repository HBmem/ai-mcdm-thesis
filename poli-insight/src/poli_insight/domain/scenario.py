from __future__ import annotations

import hashlib
import json

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self

from poli_insight.domain.enums import ScenarioType

class ScenarioRuleViolation(ValueError):
    """Raised when a scenario violates a domain rule."""
    pass

def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and value.tzinfo is None:
        raise ScenarioRuleViolation(
            f"{field_name} must include timezone information."
        )

def _canonicalize(document: dict[str, Any]) -> str:
    """Produce a stable JSON representation for hashing."""

    try:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ScenarioRuleViolation(
            "Scenario configuration is not valid JSON."
        ) from error

@dataclass(frozen=True, slots=True)
class ScenarioBundle:
    """Structured scenario configuration loaded from files."""

    scenario_id: str
    scenario_version: str
    scenario_type: ScenarioType
    title: str
    domain: str
    status: str

    scenario: dict[str, Any]
    criteria: list[dict[str, Any]]
    data_sources: dict[str, Any]
    preprocessing: dict[str, Any] | None
    session_rules: dict[str, Any]
    ui_config: dict[str, Any]

    @property
    def description(self) -> str:
        return self.scenario.get("description", "No description provided.")
    
    @property
    def alternatives(self) -> list[dict[str, Any]]:
        return self.scenario.get("alternatives", [])

    @property
    def stakeholder_groups(self) -> list[dict[str, Any]]:
        return self.scenario.get("stakeholder_groups", [])

    @property
    def scales(self) -> dict[str, Any]:
        return self.scenario.get("scales", {})

    @property
    def mcdm_methods(self) -> dict[str, Any]:
        return self.scenario.get("mcdm_methods", {})

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ScenarioRuleViolation(
                "Scenario ID cannot be empty."
            )

        if not self.scenario_version.strip():
            raise ScenarioRuleViolation(
                "Scenario version cannot be empty."
            )

        if not self.title.strip():
            raise ScenarioRuleViolation(
                "Scenario title cannot be empty."
            )

        if not self.domain.strip():
            raise ScenarioRuleViolation(
                "Scenario domain cannot be empty."
            )

        # if (self.stakeholder_groups) < 1:
        #     raise ScenarioRuleViolation(
        #         "Scenario must have at least one Stakeholder."
        #     )
        
    def snapshot_document(self) -> dict[str, Any]:
        """Return only the configuration covered by the hash."""

        return {
            "scenario": self.scenario,
            "criteria": self.criteria,
            "data_sources": self.data_sources,
            "preprocessing": self.preprocessing,
            "session_rules": self.session_rules,
            "ui_config": self.ui_config,
        }
    
    def create_snapshot(
        self,
        *,
        created_at: datetime | None = None,
    ) -> "ScenarioSnapshot":
        return ScenarioSnapshot.from_bundle(
            self,
            created_at=created_at,
        )
    
@dataclass(frozen=True, slots=True)
class ScenarioSnapshot:
    """Immutable database representation of a scenario version."""

    scenario_id: str
    scenario_version: str
    scenario_type: ScenarioType
    title: str
    domain: str
    status: str

    config_hash: str
    config_snapshot_json: str

    created_at: datetime

    @classmethod
    def from_bundle(
        cls,
        bundle: ScenarioBundle,
        *,
        created_at: datetime | None = None,
    ) -> Self:
        snapshot_json = _canonicalize(bundle.snapshot_document())

        config_hash = hashlib.sha256(
            snapshot_json.encode("utf-8")
        ).hexdigest()

        return cls(
            scenario_id=bundle.scenario_id,
            scenario_version=bundle.scenario_version,
            scenario_type=bundle.scenario_type,
            title=bundle.title,
            domain=bundle.domain,
            status=bundle.status,
            config_hash=config_hash,
            config_snapshot_json=snapshot_json,
            created_at=created_at or datetime.now(UTC),
        )
    
    def __post_init__(self) -> None:
        _require_aware_datetime(
            self.created_at,
            "created_at",
        )

        calculated_hash = hashlib.sha256(
            self.config_snapshot_json.encode("utf-8")
        ).hexdigest()

        if calculated_hash != self.config_hash:
            raise ScenarioRuleViolation(
                "Scenario snapshot hash does not match "
                "its configuration JSON."
            )
    
    def configuration(self) -> dict[str, Any]:
        """Deserialize the stored snapshot."""

        try:
            value = json.loads(self.config_snapshot_json)
        except json.JSONDecodeError as error:
            raise ScenarioRuleViolation(
                "Scenario snapshot contains invalid JSON."
            ) from error

        if not isinstance(value, dict):
            raise ScenarioRuleViolation(
                "Scenario snapshot must contain a JSON object."
            )

        return value