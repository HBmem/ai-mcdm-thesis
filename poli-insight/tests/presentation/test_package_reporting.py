from __future__ import annotations

import inspect

from streamlit.testing.v1 import AppTest

from poli_insight.presentation.streamlit.pages.admin import package_section, reports
from poli_insight.presentation.streamlit.pages.public import published_results

REPORTS_APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import PageResult
from poli_insight.domain.enum import BundleVariant, RunInclusionStatus, RunStatus
from poli_insight.presentation.streamlit.pages.admin.reports import render

now = datetime(2026, 9, 12, tzinfo=UTC)
variant_artifacts = tuple(
    SimpleNamespace(
        name=f"{variant.value}_manifest",
        variant=variant,
        content_json={
            "schema_version": 1,
            "privacy_label": variant.value,
            "completeness": [],
            "warnings": [],
        },
    )
    for variant in BundleVariant
)
artifacts = (
    SimpleNamespace(
        name="02_configuration",
        variant=None,
        content_json={"configuration_version_id": "configuration-1"},
    ),
    *variant_artifacts,
)
subject = SimpleNamespace(
    package_subject_id="subject-row-1",
    alias_snapshot="Participant 001",
    stakeholder_group_label="Residents",
    inclusion_status=RunInclusionStatus.INCLUDED,
    result_json={
        "inclusion": {"status": "included"},
        "preferences": {},
        "weights": {},
        "rankings": {},
        "stakeholder_representation": {},
        "participant_influence": {"status": "not_measured"},
    },
)
package = SimpleNamespace(
    package_run_id="package-1",
    run_number=1,
    status=RunStatus.SUCCEEDED,
    variants=(BundleVariant.ANONYMOUS, BundleVariant.PUBLIC),
    source_roster_hash="a" * 64,
    source_processing_run_id="processing-1",
    source_ranking_run_id="ranking-1",
    source_analysis_run_ids=("analysis-1",),
    source_processing_output_hash="b" * 64,
    source_ranking_output_hash="c" * 64,
    input_hash="d" * 64,
    output_hash="e" * 64,
    completed_at=now,
    artifacts=artifacts,
    subjects=(subject,),
)

class Queries:
    def list_processing_sessions(self, **arguments):
        item = SimpleNamespace(
            session_id="session-1",
            title="Transit priorities",
            current_roster_hash="a" * 64,
            active_configuration_version_id="configuration-1",
        )
        return PageResult((item,), 1, 100, 1)

class Packages:
    list_runs = SimpleNamespace(execute=lambda session_id: (package,))
    list_releases = SimpleNamespace(execute=lambda session_id: ())
    export = SimpleNamespace(
        execute=lambda run_id, variant: SimpleNamespace(
            content=b"zip", filename=f"{variant.value}.zip", media_type="application/zip"
        )
    )
    render_report = SimpleNamespace(
        execute=lambda run_id, variant: SimpleNamespace(
            content=b"html", filename=f"{variant.value}.html", media_type="text/html"
        )
    )
    release_participants = SimpleNamespace()
    withdraw_participants = SimpleNamespace()

context = SimpleNamespace(
    queries=Queries(),
    container=SimpleNamespace(
        settings=SimpleNamespace(app_timezone="UTC"),
        packages=Packages(),
    ),
    principal=SimpleNamespace(subject="admin-1"),
)
render(context)
"""


def test_package_stage_requires_explicit_variants_and_has_live_progress() -> None:
    source = inspect.getsource(package_section.render_package_stage)

    assert '"Anonymous aggregate bundle"' in source
    assert '"Public / identity-linked bundle"' in source
    assert source.count("st.progress(") == 2
    assert "st.status(" in source
    assert "value=False" in source
    assert "small-group aggregates" in source


def test_reporting_workspace_separates_variants_and_has_non_ai_exports() -> None:
    render_source = inspect.getsource(reports.render)
    variant_source = inspect.getsource(reports._variant_workspace)

    assert '"Anonymous aggregate bundle"' in render_source
    assert '"Public / identity-linked bundle"' in render_source
    assert '"Export complete bundle"' in variant_source
    assert '"Generate readable report"' in variant_source
    assert "release_participants.execute" in inspect.getsource(
        reports._participant_release_controls
    )
    assert "withdraw_participants.execute" in inspect.getsource(
        reports._participant_release_controls
    )


def test_reporting_workspace_renders_both_persisted_variants() -> None:
    app = AppTest.from_string(REPORTS_APP, default_timeout=10).run()

    assert not app.exception
    assert tuple(item.label for item in app.tabs) == (
        "Anonymous aggregate bundle",
        "Public / identity-linked bundle",
    )
    assert tuple(item.label for item in app.get("download_button")) == (
        "Export complete bundle",
        "Generate readable report",
        "Export complete bundle",
        "Generate readable report",
    )


def test_participant_result_page_offers_only_personal_report_download() -> None:
    source = inspect.getsource(published_results._render_private_result)

    assert '"Download my readable report"' in source
    assert "participant_access.execute" in source
    assert "identity map are not available" in source
    assert "Export complete bundle" not in source
