"""Processing progress derived from immutable, coherent evidence.

Navigation is transient and session-scoped; completion is always recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from poli_insight.domain.enum import ArtifactType, RunStatus, SessionStatus

STEP_TITLES = (
    "Session Validation",
    "Submission Validation",
    "Weight Generation",
    "Create Ranking",
    "Sensitivity and Robustness",
    "Package Results",
)
StepStatus = Literal[
    "ready", "running", "needs review", "failed", "complete", "stale", "unavailable"
]


@dataclass(frozen=True)
class StepState:
    title: str
    status: StepStatus
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowState:
    steps: tuple[StepState, ...]
    current: int
    weighting_id: str | None = None
    ranking_id: str | None = None
    package_id: str | None = None

    @property
    def completed(self) -> int:
        return sum(step.status == "complete" for step in self.steps)


def evaluated_cases(run: Any) -> int:
    for artifact in getattr(run, "artifacts", ()):
        if artifact.artifact_type == ArtifactType.STRUCTURED_RESULT:
            return int(
                artifact.content_json.get("summary", {}).get("evaluated_count", 0)
            )
    return sum(
        getattr(case.status, "value", case.status) == "evaluated"
        for case in getattr(run, "cases", ())
    )


def resolve_workflow(
    overview, runs=(), rankings=(), analyses=(), packages=(), *, scenario_ready=True
) -> WorkflowState:
    statuses: list[StepStatus] = ["unavailable"] * 6
    blockers: list[tuple[str, ...]] = [()] * 6
    preflight = []
    if overview.session_status not in {SessionStatus.CLOSED, SessionStatus.ARCHIVED}:
        preflight.append("Close the session to freeze its roster.")
    if not overview.has_active_configuration:
        preflight.append("Activate a session configuration.")
    if not scenario_ready:
        preflight.append("The scenario snapshot must be ready.")
    if overview.effective_submitted_count <= 0:
        preflight.append("At least one current submission is required.")
    statuses[0] = "needs review" if preflight else "complete"
    blockers[0] = tuple(preflight)
    current = 0 if preflight else 1
    weighting = ranking = package = None
    # The latest validation bundle is authoritative, including newer failed work.
    source = next(
        (run for run in runs if run.processing_run_id == overview.latest_batch_id), None
    )
    roster_current = bool(overview.roster_is_current and source is not None)
    if not preflight:
        statuses[1] = "ready"
        if overview.active_count:
            statuses[1] = "running"
        elif overview.warning_decisions_required:
            statuses[1] = "needs review"
            blockers[1] = ("Resolve every warned-submission decision.",)
        elif source is not None and not roster_current:
            statuses[1] = "stale"
            blockers[1] = ("The roster changed. Validate current submissions again.",)
        elif roster_current and overview.validation_complete:
            statuses[1] = "complete"
            current = 2
            statuses[2] = (
                "failed"
                if source.status in {RunStatus.FAILED, RunStatus.CANCELED}
                else "running"
                if source.status in {RunStatus.QUEUED, RunStatus.RUNNING}
                else "stale"
                if source.status == RunStatus.STALE
                else "ready"
            )
            if source.status == RunStatus.SUCCEEDED:
                weighting = source
                statuses[2] = "complete"
                statuses[3] = "ready"
                current = 3
    if weighting is not None:
        matching = [
            run
            for run in rankings
            if run.source_processing_run_id == weighting.processing_run_id
            and run.roster_hash == overview.current_roster_hash
        ]
        if matching and matching[0].status == RunStatus.FAILED:
            statuses[3] = "failed"
        ranking = (
            matching[0]
            if matching and matching[0].status == RunStatus.SUCCEEDED
            else None
        )
        if matching and matching[0].status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            statuses[3] = "running"
        if ranking is not None:
            statuses[3] = "complete"
            statuses[4] = "ready"
            current = 4
    if ranking is not None:
        matching_analyses = [
            run
            for run in analyses
            if run.source_ranking_run_id == ranking.ranking_run_id
        ]
        eligible = [
            run
            for run in matching_analyses
            if run.status == RunStatus.SUCCEEDED and evaluated_cases(run) > 0
        ]
        if matching_analyses and not eligible:
            statuses[4] = (
                "failed"
                if all(run.status == RunStatus.FAILED for run in matching_analyses)
                else "needs review"
            )
            blockers[4] = ("Review failed or not-evaluable cases before continuing.",)
        if eligible:
            statuses[4] = "complete"
            statuses[5] = "ready"
            current = 5
            package = next(
                (
                    run
                    for run in packages
                    if run.status == RunStatus.SUCCEEDED
                    and run.source_ranking_run_id == ranking.ranking_run_id
                    and run.source_processing_run_id == weighting.processing_run_id
                    and set(run.source_analysis_run_ids).issubset(
                        {
                            a.analysis_run_id
                            for a in matching_analyses
                            if a.status == RunStatus.SUCCEEDED
                        }
                    )
                ),
                None,
            )
            if package is not None:
                statuses[5] = "complete"
            elif any(
                run.status == RunStatus.FAILED
                and run.source_ranking_run_id == ranking.ranking_run_id
                for run in packages
            ):
                statuses[5] = "failed"
    if runs and not roster_current:
        for index in range(2, 6):
            if (runs, rankings, analyses, packages)[index - 2]:
                statuses[index] = "stale"
    return WorkflowState(
        tuple(
            StepState(title, statuses[index], blockers[index])
            for index, title in enumerate(STEP_TITLES)
        ),
        current,
        getattr(weighting, "processing_run_id", None),
        getattr(ranking, "ranking_run_id", None),
        getattr(package, "package_run_id", None),
    )


def workflow_key(session_id: str, name: str) -> str:
    return f"processing:workflow:{session_id}:{name}"


def record_completion(
    session_id: str,
    step: int,
    message: str,
    *,
    evidence_id: str | None = None,
    advance: bool = True,
) -> None:
    import streamlit as st

    st.session_state[workflow_key(session_id, "receipt")] = {
        "step": step,
        "message": message,
        "evidence_id": evidence_id,
    }
    st.session_state[workflow_key(session_id, "pending")] = {
        "step": step,
        "evidence_id": evidence_id,
        "advance": advance,
    }


def apply_pending_navigation(session_id: str, state: WorkflowState) -> None:
    import streamlit as st

    pending = st.session_state.pop(workflow_key(session_id, "pending"), None)
    if not pending:
        return
    step = pending["step"]
    lineage_id = {
        2: state.weighting_id,
        3: state.ranking_id,
        4: state.ranking_id,
        5: state.package_id,
    }.get(step)
    coherent = step < 2 or pending["evidence_id"] == lineage_id
    if pending["advance"] and coherent and state.steps[step].status == "complete":
        st.session_state[workflow_key(session_id, "viewed")] = min(step + 1, 5)
        st.session_state[workflow_key(session_id, "focus")] = True
    else:
        st.session_state[workflow_key(session_id, "viewed")] = step
