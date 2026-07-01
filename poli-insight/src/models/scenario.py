from __future__ import annotations

from dataclasses import dataclass
from typing import Any

class ScenarioConfigurationError(ValueError):
    pass

@dataclass(frozen=True)
class ScenarioBundle:
    scenario_id: str
    scenario_version: str
    scenario_type: str
    title: str
    domain: str
    scenario: dict[str, Any]
    criteria: list[dict[str, Any]]
    data_sources: dict[str, Any]
    preprocessing: dict[str, Any] | None
    session_rules: dict[str, Any]
    ui_config: dict[str, Any]

    @property
    def status(self) -> str:
        return self.scenario.get("status", "unknown")

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