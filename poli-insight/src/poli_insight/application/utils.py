from poli_insight.domain.scenario import ScenarioBundle

# Format Functions
def scenario_label(bundle: ScenarioBundle) -> str:
    return f"({bundle.scenario_version}) {bundle.title}"
