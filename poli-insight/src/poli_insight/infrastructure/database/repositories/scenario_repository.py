from sqlalchemy.orm import Session

from poli_insight.domain.enums import (
    ScenarioType
)
from poli_insight.domain.scenario import (
    ScenarioBundle,
    ScenarioRuleViolation,
    ScenarioSnapshot,
)
from poli_insight.infrastructure.database.orm_models import (
    ScenarioSnapshotRow,
)

class SqlAlchemyScenarioRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def ensure_snapshot(
        self,
        bundle: ScenarioBundle,
    ) -> ScenarioSnapshot:
        candidate = bundle.create_snapshot()

        existing = self._database_session.get(
            ScenarioSnapshotRow,
            (
                candidate.scenario_id,
                candidate.scenario_version,
            ),
        )

        if existing is not None:
            if existing.config_hash != candidate.config_hash:
                raise ScenarioRuleViolation(
                    f"Scenario {candidate.scenario_id!r} "
                    f"version {candidate.scenario_version!r} "
                    "already exists with different configuration. "
                    "Increment the scenario version."
                )

            return self._to_domain(existing)

        self._database_session.add(
            ScenarioSnapshotRow(
                scenario_id=candidate.scenario_id,
                scenario_version=candidate.scenario_version,
                scenario_type=candidate.scenario_type.value,
                title=candidate.title,
                domain=candidate.domain,
                status=candidate.status,
                config_hash=candidate.config_hash,
                config_snapshot_json=(
                    candidate.config_snapshot_json
                ),
                created_at=candidate.created_at,
            )
        )

        return candidate
    
    @staticmethod
    def _to_domain(
        row: ScenarioSnapshotRow,
    ) -> ScenarioSnapshot:
        return ScenarioSnapshot(
            scenario_id=row.scenario_id,
            scenario_version=row.scenario_version,
            scenario_type=ScenarioType(row.scenario_type),
            title=row.title,
            domain=row.domain,
            status=row.status,
            config_hash=row.config_hash,
            config_snapshot_json=row.config_snapshot_json,
            created_at=row.created_at,
        )

    def get_snapshot(
        self,
        scenario_id: str,
        scenario_version: str,
    ) -> ScenarioSnapshot | None:
        row = self._database_session.get(
            ScenarioSnapshotRow,
            (scenario_id, scenario_version),
        )

        if row is None:
            return None

        return self._to_domain(row)