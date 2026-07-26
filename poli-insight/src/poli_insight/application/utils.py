from poli_insight.domain.scenario import ScenarioBundle

import uuid

from datetime import UTC, datetime

# Format Functions
def scenario_label(bundle: ScenarioBundle) -> str:
    return f"({bundle.scenario_version}) {bundle.title}"

def _new_id(prefix: str) -> str:
    """Create a stable, unique ID for prototype records."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def _as_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)