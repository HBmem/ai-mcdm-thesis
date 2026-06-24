from __future__ import annotations

from src.utils.scenario_loader import ScenarioBundle

def scenario_label(bundle: ScenarioBundle) -> str:
    return f"({bundle.scenario_version}) {bundle.title}"