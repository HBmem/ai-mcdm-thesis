from copy import deepcopy

import pytest

from poli_insight.application.use_cases.deterministic_audit_renderer import (
    _render_participant_influence_analysis,
)


def _result(count, *, spaced=False):
    summary = {
        "case_count": count,
        "evaluated_count": count,
        "not_evaluable_count": 0,
        "maximum_rank_displacement": 0,
        "strict_reversal_count": 0,
        "top_set_change_count": 0,
        "instability_detected": False,
        "effect_distribution": {
            "session_maximum_rank_displacement_counts": {"0": count},
            "participant_identifiers_included": False,
        },
    }
    if spaced:
        summary = {
            key.replace("_", " "): (
                {k.replace("_", " "): v for k, v in value.items()}
                if isinstance(value, dict)
                else value
            )
            for key, value in summary.items()
        }
    return {"method": "participant_influence", "summary": {"summary": summary}}


def _assert_field(html, label, value):
    assert (
        f'<div class="definition-label">{label}</div>'
        f'<div class="definition-value">{value}</div>'
    ) in html


@pytest.mark.parametrize("count", [25, 41])
@pytest.mark.parametrize("spaced", [False, True])
def test_participant_influence_renders_packaged_summary(count, spaced):
    result = _result(count, spaced=spaced)
    original = deepcopy(result)
    html = _render_participant_influence_analysis(result)

    assert html.startswith('<div class="subsection"><h3>Participant Influence</h3>')
    assert '<p class="subsection-intro">' in html
    assert (
        "Individual participant cases are excluded from the shared report package."
        in html
    )
    assert '<div class="definition-grid">' in html
    assert '<div class="table-wrap"><table class="data-table">' in html
    assert "<caption>Session rank displacement distribution</caption>" in html
    assert '<th scope="col">Maximum rank displacement</th>' in html
    assert '<th scope="col">Evaluated cases</th>' in html
    for label, value in [
        ("Cases", count),
        ("Evaluated cases", count),
        ("Not evaluable cases", 0),
        ("Maximum session rank displacement", 0),
        ("Strict reversals", 0),
        ("Top-set changes", 0),
        ("Instability detected", "No"),
    ]:
        _assert_field(html, label, value)
    assert f"<tbody><tr><td>0</td><td>{count}</td></tr></tbody>" in html
    assert "No data recorded" not in html
    assert "Not recorded" not in html
    assert result == original


def test_participant_influence_sorts_distribution_numerically_and_shows_instability():
    result = _result(6)
    summary = result["summary"]["summary"]
    summary.update(
        maximum_rank_displacement=10,
        strict_reversal_count=12,
        top_set_change_count=2,
        instability_detected=True,
    )
    summary["effect_distribution"]["session_maximum_rank_displacement_counts"] = {
        "10": 1,
        "2": 2,
        "0": 3,
    }
    html = _render_participant_influence_analysis(result)

    _assert_field(html, "Maximum session rank displacement", 10)
    _assert_field(html, "Strict reversals", 12)
    _assert_field(html, "Top-set changes", 2)
    _assert_field(html, "Instability detected", "Yes")
    assert (
        "<tbody><tr><td>0</td><td>3</td></tr>"
        "<tr><td>2</td><td>2</td></tr>"
        "<tr><td>10</td><td>1</td></tr></tbody>"
    ) in html


@pytest.mark.parametrize(
    "distribution", [None, {}, {"session_maximum_rank_displacement_counts": {}}]
)
def test_missing_distribution_does_not_infer_counts_from_summary(distribution):
    result = _result(25)
    summary = result["summary"]["summary"]
    summary.pop("effect_distribution")
    if distribution is not None:
        summary["effect_distribution"] = distribution
    html = _render_participant_influence_analysis(result)

    _assert_field(html, "Evaluated cases", 25)
    assert '<p class="empty-state">No aggregate distribution recorded.</p>' in html
    assert "<table" not in html
    assert "No data recorded" not in html


@pytest.mark.parametrize("result", [{}, {"summary": {}}, {"summary": {"summary": {}}}])
def test_missing_summary_is_not_reported_as_zero(result):
    html = _render_participant_influence_analysis(result)
    assert html.count('<div class="definition-value">Not recorded</div>') == 7
    assert "No aggregate distribution recorded." in html


def test_zero_evaluated_cases_preserves_zero_and_false():
    result = _result(0)
    summary = result["summary"]["summary"]
    summary.update(case_count=1, not_evaluable_count=1)
    summary["effect_distribution"]["session_maximum_rank_displacement_counts"] = {}
    html = _render_participant_influence_analysis(result)

    _assert_field(html, "Cases", 1)
    _assert_field(html, "Evaluated cases", 0)
    _assert_field(html, "Not evaluable cases", 1)
    _assert_field(html, "Instability detected", "No")
    assert "No aggregate distribution recorded." in html


def test_participant_section_ignores_individual_cases_and_supports_flat_summary():
    result = _result(25)
    result["summary"] = result["summary"]["summary"]
    result["cases"] = [
        {
            "subject_type": "participant",
            "subject_id": "private-participant-id",
            "result": {"session_metrics": {"private-marker": 99}},
        }
    ]
    html = _render_participant_influence_analysis(result)

    _assert_field(html, "Evaluated cases", 25)
    assert "private-participant-id" not in html
    assert "private-marker" not in html
    assert "Subject" not in html
