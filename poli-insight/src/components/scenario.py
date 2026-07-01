from __future__ import annotations

from src.models.scenario import ScenarioBundle

def scenario_label(bundle: ScenarioBundle) -> str:
    return f"({bundle.scenario_version}) {bundle.title}"