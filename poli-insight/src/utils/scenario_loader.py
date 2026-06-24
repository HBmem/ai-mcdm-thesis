from __future__ import annotations

import json

from dataclasses import dataclass
from pathlib import Path
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
    folder: Path
    scenario: dict[str, Any]
    criteria: list[dict[str, Any]]
    data_sources: dict[str, Any]
    preprocessing: dict[str, Any] | None
    session_rules: dict[str, Any]
    ui_config: dict[str, Any]

    @property
    def stakeholder_groups(self) -> list[dict[str, Any]]:
        return self.scenario.get("stakeholder_groups", [])
        
def load_scenario_folder(folder: Path) -> ScenarioBundle:
    manifest_path = folder / "scenario.json"
    manifest = _read_json(manifest_path)
    _validate_scenario_manifest(manifest, folder)

    # Load criteria
    criteria_ref = manifest.get("criteria_file", "criteria.json")
    criteria_path = _safe_resolve(folder, criteria_ref)
    criteria_doc = _read_json(criteria_path) if criteria_path else {"criteria": manifest.get("criteria", [])}
    criteria = criteria_doc.get("criteria", manifest.get("criteria", []))
    _validate_criteria(criteria, manifest.get("scenario_id"))


    # Load data sources
    data_sources_ref = manifest.get("data_source_file", "data_sources.json")
    data_sources_path = _safe_resolve(folder, data_sources_ref)
    data_sources = _read_json(data_sources_path) if data_sources_path and data_sources_path.exists() else manifest.get("data_sources", {})

    # Load preprocessing
    preprocessing = None
    preprocessing_ref = manifest.get("preprocessing_file")
    if preprocessing_ref:
        preprocessing_path = _safe_resolve(folder, preprocessing_ref)
        if not preprocessing_path or not preprocessing_path.exists():
            raise ScenarioConfigurationError(f"Preprocessing file not found or invalid: {preprocessing_ref}")
        preprocessing = _read_json(preprocessing_path)
    
    # Sessions rules
    session_rules_ref = manifest.get("sessions_rules_file", "sessions_rules.json")
    session_rules_path = _safe_resolve(folder, session_rules_ref)
    session_rules = _read_json(session_rules_path) if session_rules_path and session_rules_path.exists() else manifest.get("sessions_rules", {})

    # Load UI configuration
    ui_config_ref = manifest.get("ui_config_file", "ui_config.json")
    ui_config_path = _safe_resolve(folder, ui_config_ref)
    ui_config = _read_json(ui_config_path) if ui_config_path and ui_config_path.exists() else manifest.get("ui_config", {})

    # TODO: consider saving scenario data in database
    # full_snapshot = {
    #     "scenario": manifest,
    #     "criteria": criteria,
    #     "data_sources": data_sources,
    #     "preprocessing": preprocessing,
    #     "session_rules": session_rules,
    #     "ui_config": ui_config,
    # }

    return ScenarioBundle(
        scenario_id=manifest.get("scenario_id"),
        scenario_version=manifest.get("scenario_version"),
        scenario_type=manifest.get("scenario_type"),
        title=manifest.get("title"),
        domain=manifest.get("domain"),
        folder=folder,
        scenario=manifest,
        criteria=criteria,
        data_sources=data_sources,
        preprocessing=preprocessing,
        session_rules=session_rules,
        ui_config=ui_config,
    )

def discover_scenarios(root: str | Path = "scenarios") -> tuple[list[ScenarioBundle], list[str]]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)

    scenarios: list[ScenarioBundle] = []
    errors: list[str] = []
    for folder in sorted([p for p in root_path.iterdir() if p.is_dir() and p.name != "_template"]):
        if not (folder / "scenario.json").exists():
            continue
        try:
            scenarios.append(load_scenario_folder(folder))
        except ScenarioConfigurationError as e:
            errors.append(str(e))
    return scenarios, errors

# Helper functions
def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise ScenarioConfigurationError(f"Missing config file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ScenarioConfigurationError(f"Malformed JSON in {path}: {exc}") from exc
    
def _safe_resolve(base_dir: Path, ref: str | None) -> Path | None:
    """Resolve scenario-local references while preventing ../ traversal outside the scenario folder."""
    if not ref:
        return None
    candidate = (base_dir / ref).resolve()
    base = base_dir.resolve()
    if not str(candidate).startswith(str(base)):
        raise ScenarioConfigurationError(f"Unsafe path reference outside scenario folder: {ref}")
    return candidate

def _validate_scenario_manifest(manifest: dict[str, Any], folder: Path) -> None:
    required = ["scenario_id", "scenario_version", "title", "domain", "summary", "alternatives"]
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ScenarioConfigurationError(f"{folder.name}/scenario.json is missing required fields: {missing}")
    
    alt_ids = [a.get("id") for a in manifest.get("alternatives", [])]
    if len(alt_ids) != len(set(alt_ids)):
        raise ScenarioConfigurationError(f"Duplicate alternative IDs in {folder.name}/scenario.json")
    
    group_ids = [g.get("id") for g in manifest.get("stakeholder_groups", [])]
    if len(group_ids) != len(set(group_ids)):
        raise ScenarioConfigurationError(f"Duplicate stakeholder group IDs in {folder.name}/scenario.json")

def _validate_criteria(criteria: list[dict[str, Any]], scenario_id: str) -> None:
    if not criteria:
        raise ScenarioConfigurationError(f"Scenario {scenario_id} has no criteria defined.")
    ids = [c.get("id") for c in criteria]
    if any(not c for c in ids):
        raise ScenarioConfigurationError(f"Scenario {scenario_id} has criteria without IDs")
    if len(ids) != len(set(ids)):
        raise ScenarioConfigurationError(f"Scenario {scenario_id} has duplicate criterion IDs")
    for c in criteria:
        if c.get("criteria_type") not in {"benefit", "cost"}:
            raise ScenarioConfigurationError(f"Scenario {scenario_id} has criterion with invalid type: {c.get('id')}")