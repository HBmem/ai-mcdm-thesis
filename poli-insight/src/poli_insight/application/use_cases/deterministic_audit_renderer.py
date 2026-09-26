from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
import json
from typing import Any, Callable

from poli_insight.domain.reporting import SharedReport

class _SafeHtml(str):
    """Marker type for HTML generated internally by this renderer, to avoid double-escaping."""

def _safe_html(value: str) -> _SafeHtml:
    """Mark a string as safe HTML to avoid double-escaping."""
    return _SafeHtml(value)

def _html(value: Any) -> str:
    if isinstance(value, _SafeHtml):
        return str(value)
    if value is None or value == "":
        return "Not recorded"
    return escape(str(value))

def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _first(mapping: Any, *keys: str, default: Any = None) -> Any:
    source = _mapping(mapping)
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        number = _float(value)
        if number is None:
            return None
        return int(number)


def _fmt_decimal(value: Any, places: int = 4) -> str:
    number = _float(value)
    if number is None:
        return "Not recorded" if value in (None, "") else str(value)
    return f"{number:.{places}f}"


def _fmt_number(value: Any, places: int = 2) -> str:
    number = _float(value)
    if number is None:
        return "Not recorded" if value in (None, "") else str(value)
    if abs(number - round(number)) < 1e-12:
        return f"{int(round(number)):,}"
    return f"{number:,.{places}f}"


def _fmt_fraction_percent(value: Any, places: int = 1) -> str:
    number = _float(value)
    if number is None:
        return "Not recorded"
    return f"{number * 100:.{places}f}%"


def _fmt_direct_percent(value: Any, places: int = 1) -> str:
    number = _float(value)
    if number is None:
        return "Not recorded"
    return f"{number:.{places}f}%"


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if value in (None, ""):
        return "Not recorded"
    return str(value)


def _humanize(value: Any) -> str:
    if value in (None, ""):
        return "Not recorded"
    return str(value).replace("_", " ").strip().title()


def _format_unit_value(value: Any, unit: Any) -> str:
    number = _float(value)
    if number is None:
        return "Not recorded" if value in (None, "") else str(value)

    unit_key = str(unit or "").strip().lower()
    if unit_key in {"usd", "dollar", "dollars", "currency"}:
        if abs(number - round(number)) < 1e-9:
            return f"${number:,.0f}"
        return f"${number:,.2f}"
    if unit_key in {"percentage", "percent", "%"}:
        return _fmt_direct_percent(number, 2)
    if unit_key in {"month", "months"}:
        return f"{_fmt_number(number, 2)} months"
    return _fmt_number(number, 4)


def _code(value: Any, *, css_class: str = "technical-id") -> _SafeHtml:
    if value in (None, ""):
        return _safe_html('<span class="muted">Not recorded</span>')
    return _safe_html(
        f'<code class="{escape(css_class)}">{escape(str(value))}</code>'
    )


def _badge(value: Any, tone: str = "neutral") -> _SafeHtml:
    return _safe_html(
        f'<span class="badge badge-{escape(tone)}">{escape(str(value))}</span>'
    )


def _status_badge(value: Any) -> _SafeHtml:
    text = "Not recorded" if value in (None, "") else str(value)
    lowered = text.lower()
    if lowered in {"closed", "complete", "completed", "evaluated", "current", "approved"}:
        tone = "success"
    elif lowered in {"failed", "error", "rejected", "invalid"}:
        tone = "danger"
    elif lowered in {"draft", "selected", "warning", "not_evaluable", "not evaluable"}:
        tone = "warning"
    else:
        tone = "neutral"
    return _badge(text, tone)


def _direction_badge(value: Any) -> _SafeHtml:
    direction = str(value or "Not recorded")
    lowered = direction.lower()
    tone = "success" if lowered in {"benefit", "max", "maximize"} else "warning" if lowered in {"cost", "min", "minimize"} else "neutral"
    return _badge(_humanize(direction), tone)


def _unordered_list(values: Sequence[Any]) -> _SafeHtml:
    items = _sequence(values)
    if not items:
        return _safe_html('<span class="muted">None recorded</span>')
    return _safe_html(
        "<ul class=\"compact-list\">"
        + "".join(f"<li>{_html(item)}</li>" for item in items)
        + "</ul>"
    )


def _definition_grid(rows: Sequence[tuple[str, Any]]) -> str:
    cells: list[str] = []
    for label, value in rows:
        cells.append(
            '<div class="definition-item">'
            f'<div class="definition-label">{escape(label)}</div>'
            f'<div class="definition-value">{_html(value)}</div>'
            "</div>"
        )
    return '<div class="definition-grid">' + "".join(cells) + "</div>"


def _metric_cards(rows: Sequence[tuple[str, Any, str | None]]) -> str:
    cards = []
    for label, value, note in rows:
        note_html = f'<div class="metric-note">{escape(note)}</div>' if note else ""
        cards.append(
            '<div class="metric-card">'
            f'<div class="metric-value">{_html(value)}</div>'
            f'<div class="metric-label">{escape(label)}</div>'
            f"{note_html}"
            "</div>"
        )
    return '<div class="metric-grid">' + "".join(cards) + "</div>"


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    caption: str | None = None,
    css_class: str = "",
) -> str:
    caption_html = f"<caption>{escape(caption)}</caption>" if caption else ""
    header_html = "".join(f"<th scope=\"col\">{escape(str(h))}</th>" for h in headers)
    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>" + "".join(f"<td>{_html(cell)}</td>" for cell in row) + "</tr>"
        )
    if not body_rows:
        body_rows.append(
            f'<tr><td colspan="{max(len(headers), 1)}" class="empty-cell">No data recorded.</td></tr>'
        )
    class_attr = f" data-table {css_class}".strip()
    return (
        '<div class="table-wrap">'
        f'<table class="{escape(class_attr)}">'
        f"{caption_html}<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def section(
    section_id: str,
    title: str,
    body: str,
    *,
    intro: str | None = None,
) -> str:
    intro_html = f'<p class="section-intro">{escape(intro)}</p>' if intro else ""
    return (
        f'<section id="{escape(section_id)}" class="report-section">'
        '<div class="section-heading">'
        f"<h2>{escape(title)}</h2>"
        '<a class="back-to-top" href="#top">Back to contents</a>'
        "</div>"
        f"{intro_html}{body}</section>"
    )


def _subsection(title: str, body: str, *, intro: str | None = None) -> str:
    intro_html = f'<p class="subsection-intro">{escape(intro)}</p>' if intro else ""
    return f'<div class="subsection"><h3>{escape(title)}</h3>{intro_html}{body}</div>'


def _horizontal_bar_chart(
    rows: Sequence[tuple[str, float]],
    *,
    value_formatter: Callable[[float], str] = lambda x: f"{x:.4f}",
    max_value: float | None = None,
    width: int = 920,
    row_height: int = 36,
) -> str:
    clean_rows = [(str(label), float(value)) for label, value in rows if _float(value) is not None]
    if not clean_rows:
        return '<p class="empty-state">No chartable data recorded.</p>'

    label_width = 290
    value_width = 115
    chart_width = width - label_width - value_width - 30
    height = len(clean_rows) * row_height + 18
    denominator = max_value if max_value and max_value > 0 else max((v for _, v in clean_rows), default=1.0)
    denominator = denominator or 1.0

    svg = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Bar chart">'
    ]
    for index, (label, value) in enumerate(clean_rows):
        y = index * row_height + 7
        ratio = max(0.0, min(value / denominator, 1.0))
        bar_width = ratio * chart_width
        svg.extend(
            [
                f'<text x="0" y="{y + 17}" class="chart-label">{escape(label)}</text>',
                f'<rect x="{label_width}" y="{y}" width="{chart_width}" height="20" class="chart-track" rx="3"/>',
                f'<rect x="{label_width}" y="{y}" width="{bar_width:.2f}" height="20" class="chart-bar" rx="3"/>',
                f'<text x="{label_width + chart_width + 12}" y="{y + 17}" class="chart-value">{escape(value_formatter(value))}</text>',
            ]
        )
    svg.append("</svg>")
    return '<div class="figure">' + "".join(svg) + "</div>"


def _heat_cell(value: Any, *, text: str | None = None, max_value: float = 1.0) -> _SafeHtml:
    number = _float(value)
    if number is None:
        return _safe_html('<span class="muted">—</span>')
    alpha = 0.08 + 0.52 * max(0.0, min(number / max_value if max_value else 0.0, 1.0))
    label = text if text is not None else _fmt_decimal(number, 4)
    return _safe_html(
        f'<span class="heat-cell" style="background:rgba(36,94,168,{alpha:.3f})">{escape(label)}</span>'
    )


def _rank_heat_cell(rank: Any, total: int, score: Any = None) -> _SafeHtml:
    rank_num = _int(rank)
    if rank_num is None or total <= 0:
        return _safe_html('<span class="muted">—</span>')
    strength = (total - rank_num + 1) / total
    alpha = 0.08 + 0.52 * strength
    score_text = f'<small>{escape(_fmt_decimal(score, 4))}</small>' if score is not None else ""
    return _safe_html(
        f'<span class="rank-cell" style="background:rgba(36,94,168,{alpha:.3f})">'
        f'<strong>#{rank_num}</strong>{score_text}</span>'
    )


def _render_raw_value(value: Any) -> str:
    """Recursive fallback renderer used only in audit appendices."""
    if isinstance(value, Mapping):
        if not value:
            return '<span class="muted">None recorded</span>'
        parts = ["<dl class=\"raw-dl\">"]
        for key, item in value.items():
            parts.append(f"<dt>{escape(_humanize(key))}</dt><dd>{_render_raw_value(item)}</dd>")
        parts.append("</dl>")
        return "".join(parts)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = list(value)
        if not values:
            return '<span class="muted">None recorded</span>'
        return "<ol class=\"raw-list\">" + "".join(f"<li>{_render_raw_value(item)}</li>" for item in values) + "</ol>"

    if value in (None, ""):
        return '<span class="muted">Not recorded</span>'
    return escape(str(value))


def _render_json_object(value: Any) -> str:
    """Render evidence as a pretty-printed JSON object without third-party libraries.

    Package evidence should already be JSON-compatible. The fallback to ``str`` is
    defensive for legacy/custom evidence values such as Decimal or datetime and is
    used only for the human-readable HTML projection; it does not mutate package
    evidence or any stored hashes.
    """
    try:
        payload = json.dumps(value, indent=2, ensure_ascii=False)
    except TypeError:
        payload = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return (
        '<div class="json-wrap">'
        '<pre class="json-object" aria-label="Raw evidence JSON"><code>'
        + escape(payload)
        + '</code></pre>'
        '</div>'
    )


@dataclass(frozen=True, slots=True)
class ReportLookups:
    alternatives: dict[str, str]
    alternative_order: tuple[str, ...]
    criteria: dict[str, str]
    criterion_order: tuple[str, ...]
    criterion_units: dict[str, str | None]
    criterion_directions: dict[str, str | None]
    stakeholder_groups: dict[str, str]
    stakeholder_group_order: tuple[str, ...]


def _build_report_lookups(*, context: dict, configuration: dict) -> ReportLookups:
    scenario = _mapping(_first(context, "scenario", default={}))
    alternatives = _sequence(_first(scenario, "alternatives", default=[]))
    criteria = _sequence(_first(scenario, "criteria", default=[]))
    stakeholder_groups = _sequence(
        _first(configuration, "stakeholder groups", "stakeholder_groups", default=[])
    )

    alt_rows = sorted(
        alternatives,
        key=lambda row: _int(_first(row, "display order", "display_order", default=10**9)) or 10**9,
    )
    criterion_rows = sorted(
        criteria,
        key=lambda row: _int(_first(row, "display order", "display_order", default=10**9)) or 10**9,
    )

    alt_names: dict[str, str] = {}
    alt_order: list[str] = []
    for row in alt_rows:
        alt_id = _first(row, "alternative id", "alternative_id", "id")
        if alt_id is None:
            continue
        key = str(alt_id)
        alt_names[key] = str(_first(row, "name", "key", default=key))
        alt_order.append(key)

    criterion_names: dict[str, str] = {}
    criterion_order: list[str] = []
    criterion_units: dict[str, str | None] = {}
    criterion_directions: dict[str, str | None] = {}
    for row in criterion_rows:
        criterion_id = _first(row, "criterion id", "criterion_id", "id")
        if criterion_id is None:
            continue
        key = str(criterion_id)
        criterion_names[key] = str(_first(row, "name", "key", default=key))
        criterion_units[key] = _first(row, "unit")
        criterion_directions[key] = _first(row, "direction")
        criterion_order.append(key)

    group_names: dict[str, str] = {}
    group_order: list[str] = []
    for row in stakeholder_groups:
        group_id = _first(row, "stakeholder group id", "stakeholder_group_id", "id")
        if group_id is None:
            continue
        key = str(group_id)
        group_names[key] = str(_first(row, "name", "key", default=key))
        group_order.append(key)

    return ReportLookups(
        alternatives=alt_names,
        alternative_order=tuple(alt_order),
        criteria=criterion_names,
        criterion_order=tuple(criterion_order),
        criterion_units=criterion_units,
        criterion_directions=criterion_directions,
        stakeholder_groups=group_names,
        stakeholder_group_order=tuple(group_order),
    )


def _alternative_label(alternative_id: Any, lookups: ReportLookups) -> str:
    key = str(alternative_id)
    return lookups.alternatives.get(key, key)


def _criterion_label(criterion_id: Any, lookups: ReportLookups) -> str:
    key = str(criterion_id)
    return lookups.criteria.get(key, key)


def _group_label(group_id: Any, lookups: ReportLookups) -> str:
    if group_id in (None, "", "Not recorded"):
        return "Session"
    key = str(group_id)
    return lookups.stakeholder_groups.get(key, key)


REPORT_TOC = (
    ("overview", "1. Session Overview"),
    ("scenario", "2. Scenario Definition"),
    ("configuration", "3. Session Configuration"),
    ("validation", "4. Participation & Validation"),
    ("weighting", "5. Criteria Weighting"),
    ("ranking", "6. Alternative Ranking"),
    ("analyses", "7. Sensitivity & Robustness Testing"),
    ("provenance", "8. Provenance & Reproducibility"),
    ("appendix-matrices", "Appendix A. Pairwise Matrices"),
    ("appendix-analysis-cases", "Appendix B. Detailed Analysis Cases"),
    ("appendix-raw", "Appendix C. Raw Evidence"),
)


def _render_toc() -> str:
    links = "".join(
        f'<li><a href="#{escape(section_id)}">{escape(title)}</a></li>'
        for section_id, title in REPORT_TOC
    )
    return (
        '<nav class="toc" aria-label="Table of contents">'
        "<h2>Table of Contents</h2>"
        f"<ol>{links}</ol>"
        "</nav>"
    )


def _render_report_header(report: SharedReport, context: dict, configuration: dict, validation: dict) -> str:
    scenario = _mapping(_first(context, "scenario", default={}))
    session = _mapping(_first(context, "session", default={}))
    groups = _sequence(_first(configuration, "stakeholder groups", "stakeholder_groups", default=[]))
    criteria = _sequence(_first(scenario, "criteria", default=[]))
    alternatives = _sequence(_first(scenario, "alternatives", default=[]))

    total_submissions = _first(validation, "total submission count", "total_submission_count", default=0)
    state_text = "DRAFT — not approved for publication" if report.draft else "Approved report"
    state_tone = "warning" if report.draft else "success"

    return (
        '<div id="top"></div>'
        '<header class="report-header">'
        '<div class="eyebrow">Deterministic evidence export</div>'
        f'<h1>{escape(report.title)} — Data &amp; Audit Report</h1>'
        '<div class="header-meta">'
        f'{_html(_badge(state_text, state_tone))}'
        f'<span>Revision {escape(str(report.revision.number))}</span>'
        f'<span>Session: {escape(str(_first(session, "title", default="Not recorded")))}</span>'
        "</div>"
        f'<p class="report-purpose">This report presents the fixed deterministic data, model outputs, diagnostics, sensitivity results, and provenance for audit and review. It does not contain AI-generated interpretation or policy recommendations.</p>'
        f'{_metric_cards([
            ("Submissions", _fmt_number(total_submissions, 0), None),
            ("Stakeholder groups", str(len(groups)), None),
            ("Criteria", str(len(criteria)), None),
            ("Alternatives", str(len(alternatives)), None),
            ("Session status", _status_badge(_first(session, "status", default="Not recorded")), None),
            ("Identity policy", _humanize(_first(session, "identity policy", "identity_policy", default="Not recorded")), None),
        ])}'
        '<div class="package-strip">'
        f'<span><strong>Package run:</strong> {_html(_code(report.package_run_id))}</span>'
        f'<span><strong>Package hash:</strong> {_html(_code(report.package_hash, css_class="hash"))}</span>'
        "</div>"
        "</header>"
    )


def _render_session_overview(context: dict, configuration: dict, validation: dict) -> str:
    scenario = _mapping(_first(context, "scenario", default={}))
    session = _mapping(_first(context, "session", default={}))

    policy_question = _first(scenario, "policy question", "policy_question")
    summary = _first(scenario, "summary")
    description = _first(session, "description")

    body = (
        '<div class="callout-grid">'
        '<div class="callout"><h3>Policy question</h3>'
        f'<p>{_html(policy_question)}</p></div>'
        '<div class="callout"><h3>Scenario summary</h3>'
        f'<p>{_html(summary)}</p></div>'
        "</div>"
        + _definition_grid(
            [
                ("Session title", _first(session, "title")),
                ("Session description", description),
                ("Session ID", _code(_first(session, "session id", "session_id"))),
                ("Status", _status_badge(_first(session, "status"))),
                ("Identity policy", _humanize(_first(session, "identity policy", "identity_policy"))),
                ("Lineage state", _status_badge(_first(session, "lineage state at packaging", "lineage_state_at_packaging"))),
                ("Scenario title", _first(scenario, "title")),
                ("Domain", _humanize(_first(scenario, "domain"))),
                ("Scenario snapshot ID", _code(_first(scenario, "scenario snapshot id", "scenario_snapshot_id"))),
                ("Scenario root hash", _code(_first(scenario, "root hash", "root_hash"), css_class="hash")),
                ("Schema version", _first(context, "schema version", "schema_version")),
            ]
        )
    )
    return section(
        "overview",
        "1. Session Overview",
        body,
        intro="Identifying information and the fixed decision problem represented by this package.",
    )


def _render_scenario_definition(context: dict, lookups: ReportLookups) -> str:
    scenario = _mapping(_first(context, "scenario", default={}))
    alternatives = _sequence(_first(scenario, "alternatives", default=[]))
    criteria = _sequence(_first(scenario, "criteria", default=[]))
    matrix_rows = _sequence(_first(scenario, "decision matrix", "decision_matrix", default=[]))

    alternatives = sorted(
        alternatives,
        key=lambda row: _int(_first(row, "display order", "display_order", default=10**9)) or 10**9,
    )
    criteria = sorted(
        criteria,
        key=lambda row: _int(_first(row, "display order", "display_order", default=10**9)) or 10**9,
    )

    alternative_table = render_table(
        ["Alternative", "Key", "Description", "Technical ID"],
        [
            [
                _first(row, "name"),
                _code(_first(row, "key"), css_class="short-code"),
                _first(row, "description"),
                _code(_first(row, "alternative id", "alternative_id")),
            ]
            for row in alternatives
        ],
    )

    criteria_table = render_table(
        ["Criterion", "Direction", "Unit", "Description", "Technical ID"],
        [
            [
                _first(row, "name"),
                _direction_badge(_first(row, "direction")),
                _humanize(_first(row, "unit")),
                _first(row, "description"),
                _code(_first(row, "criterion id", "criterion_id")),
            ]
            for row in criteria
        ],
    )

    values: dict[tuple[str, str], Any] = {}
    for row in matrix_rows:
        alt_id = _first(row, "alternative id", "alternative_id")
        criterion_id = _first(row, "criterion id", "criterion_id")
        if alt_id is None or criterion_id is None:
            continue
        values[(str(alt_id), str(criterion_id))] = _first(row, "value", "value json", "value_json")

    criterion_ids = list(lookups.criterion_order)
    alternative_ids = list(lookups.alternative_order)
    matrix_headers = ["Alternative"] + [lookups.criteria.get(cid, cid) for cid in criterion_ids]
    matrix_table_rows = []
    for alt_id in alternative_ids:
        cells: list[Any] = [lookups.alternatives.get(alt_id, alt_id)]
        for criterion_id in criterion_ids:
            value = values.get((alt_id, criterion_id))
            cells.append(_format_unit_value(value, lookups.criterion_units.get(criterion_id)))
        matrix_table_rows.append(cells)

    decision_matrix = render_table(
        matrix_headers,
        matrix_table_rows,
        caption="Decision matrix values as packaged for the scenario.",
        css_class="matrix-table",
    )

    body = (
        _subsection("Alternatives", alternative_table)
        + _subsection("Criteria", criteria_table)
        + _subsection(
            "Decision Matrix",
            decision_matrix,
            intro="Rows are alternatives and columns are evaluation criteria. Display formatting does not alter the stored evidence values.",
        )
    )
    return section("scenario", "2. Scenario Definition", body)


def _render_configuration(configuration: dict, lookups: ReportLookups) -> str:
    algorithms = _sequence(_first(configuration, "algorithms", default=[]))
    groups = _sequence(_first(configuration, "stakeholder groups", "stakeholder_groups", default=[]))
    required_policy = _mapping(_first(configuration, "required group policy", "required_group_policy", default={}))

    core = _definition_grid(
        [
            ("Response format", _humanize(_first(configuration, "response format", "response_format"))),
            ("Consistency threshold", _fmt_decimal(_first(configuration, "consistency threshold", "consistency_threshold"), 4)),
            ("Missing group policy", _humanize(_first(configuration, "missing group policy", "missing_group_policy"))),
            ("Configuration version ID", _code(_first(configuration, "configuration version id", "configuration_version_id"))),
            ("Configuration hash", _code(_first(configuration, "configuration hash", "configuration_hash"), css_class="hash")),
            ("Schema version", _first(configuration, "schema version", "schema_version")),
        ]
    )

    algorithm_table = render_table(
        ["Role", "Implementation", "Parameters", "Parameter hash"],
        [
            [
                _humanize(_first(row, "role")),
                _code(_first(row, "implementation id", "implementation_id")),
                _safe_html(_render_raw_value(_first(row, "parameters", default={}))),
                _code(_first(row, "parameter hash", "parameter_hash"), css_class="hash"),
            ]
            for row in algorithms
        ],
    )

    group_table_rows = []
    participant_chart: list[tuple[str, float]] = []
    voting_chart: list[tuple[str, float]] = []
    for row in groups:
        group_id = _first(row, "stakeholder group id", "stakeholder_group_id")
        name = _first(row, "name", default=_group_label(group_id, lookups))
        count = _first(row, "included participant count", "included_participant_count", default=0)
        voting_power = _first(row, "configured voting power", "configured_voting_power")
        effective_voting_power = _first(
            row, "effective voting power", "effective_voting_power"
        )
        group_table_rows.append(
            [
                name,
                _code(_first(row, "key"), css_class="short-code"),
                _fmt_fraction_percent(voting_power, 1),
                _fmt_fraction_percent(effective_voting_power, 1),
                _fmt_number(_first(row, "configured allocation units", "configured_allocation_units"), 0),
                _fmt_number(count, 0),
                _fmt_bool(_first(row, "small group warning", "small_group_warning")),
                _code(group_id),
            ]
        )
        if _float(count) is not None:
            participant_chart.append((str(name), float(count)))
        if _float(voting_power) is not None:
            voting_chart.append((str(name), float(voting_power)))

    group_table = render_table(
        [
            "Stakeholder group",
            "Key",
            "Configured voting power",
            "Effective voting power",
            "Allocation units",
            "Included participants",
            "Small-group warning",
            "Technical ID",
        ],
        group_table_rows,
    )

    required_keys = _sequence(_first(required_policy, "required group keys", "required_group_keys", default=[]))
    required_html = _unordered_list([_humanize(key) for key in required_keys])

    body = (
        _subsection("Core Configuration", core)
        + _subsection("Configured Algorithms", algorithm_table)
        + _subsection(
            "Stakeholder Configuration",
            '<div class="chart-pair">'
            '<div><h4>Included participants</h4>'
            + _horizontal_bar_chart(participant_chart, value_formatter=lambda v: _fmt_number(v, 0))
            + '</div><div><h4>Configured voting power</h4>'
            + _horizontal_bar_chart(voting_chart, value_formatter=lambda v: _fmt_fraction_percent(v, 1), max_value=1.0)
            + "</div></div>"
            + group_table,
        )
        + _subsection("Required Stakeholder Groups", _html(required_html))
    )
    return section("configuration", "3. Session Configuration", body)


def _render_validation(validation: dict, configuration: dict, lookups: ReportLookups) -> str:
    total = _int(_first(validation, "total submission count", "total_submission_count", default=0)) or 0
    inclusion_counts = _mapping(_first(validation, "inclusion counts", "inclusion_counts", default={}))
    included = _int(_first(inclusion_counts, "included", default=0)) or 0
    explicit_excluded = _int(_first(inclusion_counts, "excluded"))
    excluded = explicit_excluded if explicit_excluded is not None else max(total - included, 0)

    group_counts = _sequence(_first(validation, "group included counts", "group_included_counts", default=[]))
    exclusion_counts = _mapping(_first(validation, "exclusion reason counts", "exclusion_reason_counts", default={}))

    group_rows = []
    chart_rows: list[tuple[str, float]] = []
    for row in group_counts:
        name = _first(row, "stakeholder group", "stakeholder_group", default="Not recorded")
        count = _first(row, "count", default=0)
        group_rows.append([name, _fmt_number(count, 0)])
        if _float(count) is not None:
            chart_rows.append((str(name), float(count)))

    represented_groups = sum(1 for _, count in chart_rows if count > 0)
    cards = _metric_cards(
        [
            ("Total submissions", _fmt_number(total, 0), None),
            ("Included", _fmt_number(included, 0), None),
            ("Excluded", _fmt_number(excluded, 0), None),
            ("Groups represented", str(represented_groups), None),
        ]
    )

    exclusions = [
        [_humanize(reason), _fmt_number(count, 0)]
        for reason, count in exclusion_counts.items()
    ]

    body = (
        cards
        + _subsection(
            "Included Participants by Stakeholder Group",
            _horizontal_bar_chart(chart_rows, value_formatter=lambda v: _fmt_number(v, 0))
            + render_table(["Stakeholder group", "Included count"], group_rows),
        )
        + _subsection(
            "Exclusions",
            render_table(["Reason", "Count"], exclusions),
        )
        + _subsection(
            "Validation Provenance",
            _definition_grid(
                [
                    ("Roster hash", _code(_first(validation, "roster hash", "roster_hash"), css_class="hash")),
                    ("Schema version", _first(validation, "schema version", "schema_version")),
                ]
            ),
        )
    )
    return section(
        "validation",
        "4. Participation & Validation",
        body,
        intro="Submission inclusion, stakeholder representation, and validation metadata recorded before deterministic processing.",
    )


def _extract_weights(record: Mapping[str, Any]) -> dict[str, float]:
    weight_wrapper = _mapping(_first(record, "weights", default={}))
    values = _sequence(_first(weight_wrapper, "values", default=[]))
    result: dict[str, float] = {}
    for row in values:
        criterion_id = _first(row, "criterion id", "criterion_id")
        weight = _float(_first(row, "weight"))
        if criterion_id is not None and weight is not None:
            result[str(criterion_id)] = weight
    return result


def _weighting_scope_label(record: Mapping[str, Any], lookups: ReportLookups) -> str:
    level = str(_first(record, "level", default="Not recorded"))
    if level == "session":
        return "Session aggregate"
    if level == "stakeholder_group":
        return _group_label(_first(record, "stakeholder group id", "stakeholder_group_id"), lookups)
    return _humanize(level)


def _render_weighting(weighting: dict, lookups: ReportLookups) -> str:
    records = _sequence(_first(weighting, "aggregate matrices", "aggregate_matrices", default=[]))
    session_record = next((r for r in records if _first(r, "level") == "session"), None)

    parts: list[str] = []
    if session_record:
        session_weights = _extract_weights(_mapping(session_record))
        chart_rows = [
            (lookups.criteria.get(cid, cid), session_weights[cid])
            for cid in lookups.criterion_order
            if cid in session_weights
        ]
        parts.append(
            _subsection(
                "Session Aggregate Weights",
                _horizontal_bar_chart(
                    chart_rows,
                    value_formatter=lambda v: _fmt_fraction_percent(v, 2),
                    max_value=1.0,
                )
                + render_table(
                    ["Criterion", "Weight", "Direction"],
                    [
                        [
                            label,
                            _fmt_fraction_percent(value, 4),
                            _direction_badge(lookups.criterion_directions.get(cid)),
                        ]
                        for cid, (label, value) in zip(
                            [cid for cid in lookups.criterion_order if cid in session_weights],
                            chart_rows,
                        )
                    ],
                ),
                intro="Displayed weights are the fixed session-level values contained in the package.",
            )
        )

    matrix_headers = ["Scope"] + [lookups.criteria.get(cid, cid) for cid in lookups.criterion_order]
    matrix_rows: list[list[Any]] = []
    ordered_records = sorted(
        records,
        key=lambda row: (
            1 if _first(row, "level") == "session" else 0,
            _weighting_scope_label(_mapping(row), lookups),
        ),
    )
    for record in ordered_records:
        weights = _extract_weights(_mapping(record))
        row: list[Any] = [_weighting_scope_label(_mapping(record), lookups)]
        for cid in lookups.criterion_order:
            value = weights.get(cid)
            row.append(_heat_cell(value, text=_fmt_fraction_percent(value, 1) if value is not None else None))
        matrix_rows.append(row)

    parts.append(
        _subsection(
            "Weight Comparison by Scope",
            render_table(matrix_headers, matrix_rows, css_class="heat-table"),
            intro="Cell shading provides a visual comparison only; exact values are printed in each cell.",
        )
    )

    diagnostic_rows = []
    for record in ordered_records:
        diagnostics = _mapping(_first(record, "diagnostics", default={}))
        diagnostic_rows.append(
            [
                _weighting_scope_label(_mapping(record), lookups),
                _humanize(_first(diagnostics, "method")),
                _first(diagnostics, "provider"),
                _fmt_decimal(_first(diagnostics, "consistency ratio", "consistency_ratio"), 6),
                _fmt_decimal(_first(diagnostics, "consistency threshold", "consistency_threshold"), 4),
                _fmt_bool(_first(diagnostics, "threshold exceeded", "threshold_exceeded")),
                _humanize(_first(diagnostics, "weight derivation", "weight_derivation")),
                _code(_first(record, "matrix hash", "matrix_hash"), css_class="hash"),
            ]
        )

    parts.append(
        _subsection(
            "Weighting Diagnostics",
            render_table(
                [
                    "Scope",
                    "Method",
                    "Provider",
                    "Consistency ratio",
                    "Threshold",
                    "Exceeded",
                    "Derivation",
                    "Matrix hash",
                ],
                diagnostic_rows,
            ),
        )
    )

    parts.append(
        _subsection(
            "Weighting Run Metadata",
            _definition_grid(
                [
                    ("Processing run ID", _code(_first(weighting, "processing run id", "processing_run_id"))),
                    ("Input hash", _code(_first(weighting, "input hash", "input_hash"), css_class="hash")),
                    ("Output hash", _code(_first(weighting, "output hash", "output_hash"), css_class="hash")),
                    ("Schema version", _first(weighting, "schema version", "schema_version")),
                ]
            ),
        )
    )

    return section(
        "weighting",
        "5. Criteria Weighting",
        "".join(parts),
        intro="AHP or other configured weighting outputs, shown at stakeholder-group and session aggregation levels.",
    )


def _ranking_rows(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = [_mapping(row) for row in _sequence(_first(record, "alternatives", default=[]))]
    return sorted(rows, key=lambda row: _int(_first(row, "rank", default=10**9)) or 10**9)


def _ranking_scope_label(record: Mapping[str, Any], lookups: ReportLookups) -> str:
    level = str(_first(record, "level", default="Not recorded"))
    if level == "session":
        return "Session aggregate"
    if level == "stakeholder_group":
        return _group_label(_first(record, "stakeholder group id", "stakeholder_group_id"), lookups)
    return _humanize(level)


def _render_ranking(ranking: dict, lookups: ReportLookups) -> str:
    results = _sequence(_first(ranking, "aggregate results", "aggregate_results", default=[]))
    session_result = next((r for r in results if _first(r, "level") == "session"), None)
    parts: list[str] = []

    if session_result:
        rows = _ranking_rows(_mapping(session_result))
        chart_rows = [
            (_alternative_label(_first(row, "alternative id", "alternative_id"), lookups), float(_first(row, "preference value", "preference_value")))
            for row in rows
            if _float(_first(row, "preference value", "preference_value")) is not None
        ]
        metric_label = _first(session_result, "metric label", "metric_label", default="Preference value")
        result_table = render_table(
            ["Rank", "Alternative", str(metric_label), "Alternative ID"],
            [
                [
                    _first(row, "rank"),
                    _alternative_label(_first(row, "alternative id", "alternative_id"), lookups),
                    _fmt_decimal(_first(row, "preference value", "preference_value"), 6),
                    _code(_first(row, "alternative id", "alternative_id")),
                ]
                for row in rows
            ],
        )
        parts.append(
            _subsection(
                "Session Aggregate Ranking",
                _horizontal_bar_chart(chart_rows, value_formatter=lambda v: _fmt_decimal(v, 6), max_value=1.0)
                + result_table,
                intro="Alternatives are ordered exactly as produced by the configured ranking method.",
            )
        )

        diagnostics = _mapping(_first(session_result, "diagnostics", default={}))
        algorithm_meta = _mapping(_first(diagnostics, "algorithm metadata", "algorithm_metadata", default={}))
        parts.append(
            _subsection(
                "Session Ranking Diagnostics",
                _definition_grid(
                    [
                        ("Method", _humanize(_first(algorithm_meta, "method"))),
                        ("Provider", _first(algorithm_meta, "provider")),
                        ("Adapter version", _first(algorithm_meta, "adapter version", "adapter_version")),
                        ("Alternative count", _first(diagnostics, "alternative count", "alternative_count")),
                        ("Criterion count", _first(diagnostics, "criterion count", "criterion_count")),
                        ("Criterion directions", _unordered_list([_humanize(v) for v in _sequence(_first(diagnostics, "criterion directions", "criterion_directions", default=[]))])),
                        ("Result hash", _code(_first(session_result, "result hash", "result_hash"), css_class="hash")),
                    ]
                ),
            )
        )

    total_alternatives = max(len(lookups.alternative_order), 1)
    rank_headers = ["Scope"] + [lookups.alternatives.get(aid, aid) for aid in lookups.alternative_order]
    rank_matrix_rows: list[list[Any]] = []
    ordered_results = sorted(
        results,
        key=lambda row: (
            1 if _first(row, "level") == "session" else 0,
            _ranking_scope_label(_mapping(row), lookups),
        ),
    )
    for result in ordered_results:
        by_alt = {
            str(_first(row, "alternative id", "alternative_id")): row
            for row in _ranking_rows(_mapping(result))
        }
        rendered: list[Any] = [_ranking_scope_label(_mapping(result), lookups)]
        for alt_id in lookups.alternative_order:
            row = by_alt.get(alt_id)
            if row is None:
                rendered.append(_safe_html('<span class="muted">—</span>'))
            else:
                rendered.append(
                    _rank_heat_cell(
                        _first(row, "rank"),
                        total_alternatives,
                        _first(row, "preference value", "preference_value"),
                    )
                )
        rank_matrix_rows.append(rendered)

    parts.append(
        _subsection(
            "Ranking Comparison by Scope",
            render_table(rank_headers, rank_matrix_rows, css_class="heat-table rank-matrix"),
            intro="Each cell shows rank and preference value. Darker shading indicates a higher rank within that scope.",
        )
    )

    parts.append(
        _subsection(
            "Ranking Run Metadata",
            _definition_grid(
                [
                    ("Ranking run ID", _code(_first(ranking, "ranking run id", "ranking_run_id"))),
                    ("Implementation ID", _code(_first(ranking, "implementation id", "implementation_id"))),
                    ("Implementation version", _first(ranking, "implementation version", "implementation_version")),
                    ("Adapter version", _first(ranking, "adapter version", "adapter_version")),
                    ("Input hash", _code(_first(ranking, "input hash", "input_hash"), css_class="hash")),
                    ("Output hash", _code(_first(ranking, "output hash", "output_hash"), css_class="hash")),
                    ("Schema version", _first(ranking, "schema version", "schema_version")),
                ]
            ),
        )
    )

    return section(
        "ranking",
        "6. Alternative Ranking",
        "".join(parts),
        intro="Session and stakeholder-group ranking outputs from the configured deterministic ranking method.",
    )


def _analysis_summary_metrics(result: Mapping[str, Any]) -> Mapping[str, Any]:
    outer = _mapping(_first(result, "summary", default={}))
    inner = _mapping(_first(outer, "summary", default={}))
    return inner or outer


def _analysis_cases(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [_mapping(case) for case in _sequence(_first(result, "cases", default=[]))]


def _case_metrics(case: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the primary comparison metrics for any analysis case.

    New participant-influence packages normalize the session effect to
    ``result.metrics``. The ``session_metrics`` fallback keeps previously created
    packages renderable without rebundling them.
    """
    result = _mapping(_first(case, "result", default={}))
    metrics = _mapping(_first(result, "metrics", default={}))
    if metrics:
        return metrics
    return _mapping(
        _first(result, "session metrics", "session_metrics", default={})
    )


def _case_ranking(case: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the primary reranking for any analysis case with legacy fallback."""
    result = _mapping(_first(case, "result", default={}))
    ranking = _sequence(_first(result, "ranking", default=[]))
    if not ranking:
        ranking = _sequence(
            _first(result, "session ranking", "session_ranking", default=[])
        )
    return [_mapping(row) for row in ranking]


def _winner_from_ranking(
    ranking: Sequence[Mapping[str, Any]],
    lookups: ReportLookups,
) -> str:
    if not ranking:
        return "Not recorded"
    winner = min(
        ranking,
        key=lambda row: _int(_first(row, "rank", default=10**9)) or 10**9,
    )
    return _alternative_label(
        _first(winner, "alternative id", "alternative_id"), lookups
    )


def _case_winner(case: Mapping[str, Any], lookups: ReportLookups) -> str:
    return _winner_from_ranking(_case_ranking(case), lookups)


def _scope_label(case: Mapping[str, Any], lookups: ReportLookups) -> str:
    scope_type = str(_first(case, "scope type", "scope_type", default="Not recorded"))
    scope_id = _first(case, "scope id", "scope_id")
    if scope_type == "session":
        return "Session"
    if scope_type == "stakeholder_group":
        return _group_label(scope_id, lookups)
    if scope_type == "participant":
        # Shared audit reports intentionally avoid rendering participant identifiers.
        return "Participant"
    return _humanize(scope_type) if scope_id in (None, "") else f"{_humanize(scope_type)}: {scope_id}"


def _subject_label(case: Mapping[str, Any], lookups: ReportLookups) -> str:
    subject_type = str(_first(case, "subject type", "subject_type", default="Not recorded"))
    subject_id = _first(case, "subject id", "subject_id")
    if subject_type == "criterion":
        return _criterion_label(subject_id, lookups)
    if subject_type == "alternative":
        return _alternative_label(subject_id, lookups)
    if subject_type == "stakeholder_group":
        return _group_label(subject_id, lookups)
    if subject_type == "participant":
        # The case sequence identifies the audit record without exposing a participant ID.
        return "Participant"
    if subject_id in (None, "", "Not recorded"):
        return _humanize(subject_type)
    return str(subject_id)


def _render_analysis_coverage(analyses: dict) -> str:
    rows = _sequence(_first(analyses, "completeness", default=[]))
    return render_table(
        ["Analysis method", "State"],
        [
            [
                _humanize(_first(row, "method")),
                _status_badge(_first(row, "state")),
            ]
            for row in rows
        ],
    )


def _render_analysis_overview(results: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for result in results:
        summary = _analysis_summary_metrics(result)
        warning_counts = _mapping(
            _first(result, "warning counts", "warning_counts", default={})
        )
        warning_total = sum(
            _int(value) or 0 for value in warning_counts.values()
        )
        rows.append(
            [
                _humanize(_first(result, "method")),
                _fmt_number(_first(summary, "case count", "case_count"), 0),
                _fmt_number(_first(summary, "evaluated count", "evaluated_count"), 0),
                _fmt_number(_first(summary, "not evaluable count", "not_evaluable_count"), 0),
                _fmt_number(_first(summary, "maximum rank displacement", "maximum_rank_displacement"), 0),
                _fmt_number(_first(summary, "strict reversal count", "strict_reversal_count"), 0),
                _fmt_number(_first(summary, "top set change count", "top_set_change_count"), 0),
                _fmt_bool(_first(summary, "instability detected", "instability_detected")),
                _fmt_number(warning_total, 0),
                _code(_first(result, "analysis run id", "analysis_run_id")),
            ]
        )
    return render_table(
        [
            "Method",
            "Cases",
            "Evaluated",
            "Not evaluable",
            "Max displacement",
            "Strict reversals",
            "Top-set changes",
            "Instability detected",
            "Warnings",
            "Run ID",
        ],
        rows,
    )


def _render_weight_perturbation_analysis(result: Mapping[str, Any], lookups: ReportLookups) -> str:
    buckets: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for case in _analysis_cases(result):
        key = (
            str(_first(case, "scope type", "scope_type", default="")),
            str(_first(case, "scope id", "scope_id", default="")),
            str(_first(case, "subject type", "subject_type", default="")),
            str(_first(case, "subject id", "subject_id", default="")),
        )
        buckets[key].append(case)

    table_rows = []
    for cases in buckets.values():
        first_case = cases[0]
        evaluated = [case for case in cases if _case_metrics(case)]
        candidate_weights = [
            _float(_first(_mapping(_first(case, "input", default={})), "candidate weight", "candidate_weight"))
            for case in cases
        ]
        candidate_weights = [v for v in candidate_weights if v is not None]
        baseline = _float(
            _first(_mapping(_first(first_case, "input", default={})), "baseline weight", "baseline_weight")
        )
        spearman = [_float(_first(_case_metrics(case), "spearman")) for case in evaluated]
        spearman = [v for v in spearman if v is not None]
        kendall = [_float(_first(_case_metrics(case), "kendall tau b", "kendall_tau_b")) for case in evaluated]
        kendall = [v for v in kendall if v is not None]
        displacement = [_int(_first(_case_metrics(case), "maximum rank displacement", "maximum_rank_displacement")) for case in evaluated]
        displacement = [v for v in displacement if v is not None]
        reversals = sum(_int(_first(_case_metrics(case), "strict reversals", "strict_reversals", default=0)) or 0 for case in evaluated)
        top_changes = sum(bool(_first(_case_metrics(case), "top set changed", "top_set_changed", default=False)) for case in evaluated)
        retention_values = [
            _first(_case_metrics(case), "top choice retained", "top_choice_retained")
            for case in evaluated
            if _first(_case_metrics(case), "top choice retained", "top_choice_retained") is not None
        ]
        retention_rate = (
            sum(bool(v) for v in retention_values) / len(retention_values)
            if retention_values
            else None
        )
        tested_range = (
            f"{_fmt_fraction_percent(min(candidate_weights), 1)} – {_fmt_fraction_percent(max(candidate_weights), 1)}"
            if candidate_weights
            else "Not recorded"
        )
        table_rows.append(
            [
                _scope_label(first_case, lookups),
                _subject_label(first_case, lookups),
                _fmt_fraction_percent(baseline, 2) if baseline is not None else "Not recorded",
                tested_range,
                str(len(cases)),
                str(len(evaluated)),
                _fmt_decimal(min(spearman), 3) if spearman else "Not recorded",
                _fmt_decimal(min(kendall), 3) if kendall else "Not recorded",
                str(max(displacement)) if displacement else "Not recorded",
                str(reversals),
                str(top_changes),
                _fmt_fraction_percent(retention_rate, 1) if retention_rate is not None else "Not recorded",
            ]
        )

    table_rows.sort(key=lambda row: (str(row[0]), str(row[1])))
    return _subsection(
        "One-at-a-Time Weight Perturbation",
        render_table(
            [
                "Scope",
                "Criterion",
                "Baseline weight",
                "Tested range",
                "Cases",
                "Evaluated",
                "Min Spearman",
                "Min Kendall τ-b",
                "Max displacement",
                "Strict reversals",
                "Top-set changes",
                "Top-choice retention",
            ],
            table_rows,
        ),
        intro="Cases are grouped by analysis scope and perturbed criterion so the main report remains reviewable; every individual case is preserved in Appendix B.",
    )


def _render_criterion_removal_analysis(result: Mapping[str, Any], lookups: ReportLookups) -> str:
    rows = []
    for case in _analysis_cases(result):
        inputs = _mapping(_first(case, "input", default={}))
        metrics = _case_metrics(case)
        removed_id = _first(inputs, "removed criterion id", "removed_criterion_id", default=_first(case, "subject id", "subject_id"))
        rows.append(
            [
                _scope_label(case, lookups),
                _criterion_label(removed_id, lookups),
                _status_badge(_first(case, "status")),
                _case_winner(case, lookups),
                _fmt_decimal(_first(metrics, "spearman"), 3),
                _fmt_decimal(_first(metrics, "kendall tau b", "kendall_tau_b"), 3),
                _fmt_number(_first(metrics, "maximum rank displacement", "maximum_rank_displacement"), 0),
                _fmt_number(_first(metrics, "strict reversals", "strict_reversals"), 0),
                _fmt_bool(_first(metrics, "top choice retained", "top_choice_retained")),
                _fmt_bool(_first(metrics, "top set changed", "top_set_changed")),
                _fmt_decimal(_first(metrics, "candidate score margin", "candidate_score_margin"), 6),
            ]
        )
    return _subsection(
        "Criterion Removal",
        render_table(
            [
                "Scope",
                "Removed criterion",
                "Status",
                "Resulting winner",
                "Spearman",
                "Kendall τ-b",
                "Max displacement",
                "Strict reversals",
                "Top retained",
                "Top set changed",
                "Candidate margin",
            ],
            rows,
        ),
    )


def _render_rank_reversal_analysis(result: Mapping[str, Any], lookups: ReportLookups) -> str:
    rows = []
    for case in _analysis_cases(result):
        inputs = _mapping(_first(case, "input", default={}))
        metrics = _case_metrics(case)
        removed_id = _first(inputs, "removed alternative id", "removed_alternative_id", default=_first(case, "subject id", "subject_id"))
        rows.append(
            [
                _scope_label(case, lookups),
                _alternative_label(removed_id, lookups),
                _status_badge(_first(case, "status")),
                _case_winner(case, lookups),
                _fmt_decimal(_first(metrics, "spearman"), 3),
                _fmt_decimal(_first(metrics, "kendall tau b", "kendall_tau_b"), 3),
                _fmt_number(_first(metrics, "maximum rank displacement", "maximum_rank_displacement"), 0),
                _fmt_number(_first(metrics, "strict reversals", "strict_reversals"), 0),
                _fmt_bool(_first(metrics, "top choice retained", "top_choice_retained")),
                _fmt_bool(_first(metrics, "top set changed", "top_set_changed")),
            ]
        )
    return _subsection(
        "Rank Reversal",
        render_table(
            [
                "Scope",
                "Removed alternative",
                "Status",
                "Resulting winner",
                "Spearman",
                "Kendall τ-b",
                "Max displacement",
                "Strict reversals",
                "Top retained",
                "Top set changed",
            ],
            rows,
        ),
    )


def _render_influence_analysis(
    title: str,
    result: Mapping[str, Any],
    lookups: ReportLookups,
) -> str:
    rows = []
    for case in _analysis_cases(result):
        metrics = _case_metrics(case)
        warnings = _sequence(_first(case, "warnings", default=[]))
        rows.append(
            [
                _scope_label(case, lookups),
                _subject_label(case, lookups),
                _status_badge(_first(case, "status")),
                _case_winner(case, lookups),
                _fmt_decimal(_first(metrics, "spearman"), 3),
                _fmt_decimal(_first(metrics, "kendall tau b", "kendall_tau_b"), 3),
                _fmt_number(_first(metrics, "maximum rank displacement", "maximum_rank_displacement"), 0),
                _fmt_number(_first(metrics, "strict reversals", "strict_reversals"), 0),
                _fmt_bool(_first(metrics, "top choice retained", "top_choice_retained")),
                _fmt_bool(_first(metrics, "top set changed", "top_set_changed")),
                "; ".join(str(w) for w in warnings) if warnings else "None",
            ]
        )
    return _subsection(
        title,
        render_table(
            [
                "Scope",
                "Subject",
                "Status",
                "Resulting winner",
                "Spearman",
                "Kendall τ-b",
                "Max displacement",
                "Strict reversals",
                "Top retained",
                "Top set changed",
                "Warnings",
            ],
            rows,
        ),
    )


def _participant_group_effect(
    case: Mapping[str, Any],
) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], Mapping[str, Any]]:
    """Return stakeholder-group metrics, ranking and weighting diagnostics.

    Supports both the normalized package projection and legacy participant
    influence cases that stored ``group_*`` fields directly on result.
    """
    result = _mapping(_first(case, "result", default={}))
    effect = _mapping(
        _first(
            result,
            "stakeholder group effect",
            "stakeholder_group_effect",
            default={},
        )
    )

    metrics = _mapping(_first(effect, "metrics", default={}))
    if not metrics:
        metrics = _mapping(
            _first(result, "group metrics", "group_metrics", default={})
        )

    ranking = _sequence(_first(effect, "ranking", default=[]))
    if not ranking:
        ranking = _sequence(
            _first(result, "group ranking", "group_ranking", default=[])
        )

    diagnostics = _mapping(
        _first(
            effect,
            "weighting diagnostics",
            "weighting_diagnostics",
            default={},
        )
    )
    if not diagnostics:
        diagnostics = _mapping(
            _first(
                result,
                "group weighting diagnostics",
                "group_weighting_diagnostics",
                default={},
            )
        )

    return metrics, [_mapping(row) for row in ranking], diagnostics


def _participant_session_weighting_diagnostics(
    case: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return session weighting diagnostics from normalized or legacy cases."""
    result = _mapping(_first(case, "result", default={}))
    diagnostics = _mapping(
        _first(
            result,
            "weighting diagnostics",
            "weighting_diagnostics",
            default={},
        )
    )
    if diagnostics:
        return diagnostics
    return _mapping(
        _first(
            result,
            "session weighting diagnostics",
            "session_weighting_diagnostics",
            default={},
        )
    )


def _render_ranking_rows(
    rows: Sequence[Mapping[str, Any]],
    lookups: ReportLookups,
) -> str:
    """Render a compact deterministic ranking table used by analysis appendices."""
    if not rows:
        return '<p class="empty-state">No ranking recorded.</p>'
    ordered = sorted(
        rows,
        key=lambda row: _int(_first(row, "rank", default=10**9)) or 10**9,
    )
    return render_table(
        ["Rank", "Alternative", "Preference value"],
        [
            [
                _first(row, "rank"),
                _alternative_label(
                    _first(row, "alternative id", "alternative_id"), lookups
                ),
                _fmt_decimal(
                    _first(row, "preference value", "preference_value"), 6
                ),
            ]
            for row in ordered
        ],
    )


def _participant_identifiers_included(result: Mapping[str, Any]) -> bool | None:
    """Return whether participant identifiers are included in the packaged analysis."""
    summary = _analysis_summary_metrics(result)
    distribution = _mapping(
        _first(summary, "effect distribution", "effect_distribution", default={})
    )

    for source in (result, _mapping(_first(result, "summary", default={})), summary, distribution):
        value = _first(
            source,
            "participant identifiers included",
            "participant_identifiers_included",
        )
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _participant_case_label(case: Mapping[str, Any], fallback_index: int) -> str:
    """Create a stable privacy-safe label for a participant influence case."""
    sequence = _first(case, "sequence")
    if sequence not in (None, ""):
        return f"Participant case {sequence}"
    return f"Participant case {fallback_index}"


def _participant_case_group(case: Mapping[str, Any], lookups: ReportLookups) -> str:
    """Resolve a participant case's stakeholder group when the package records it."""
    inputs = _mapping(_first(case, "input", default={}))
    result = _mapping(_first(case, "result", default={}))

    group_id = _first(
        case,
        "stakeholder group id",
        "stakeholder_group_id",
        default=_first(
            inputs,
            "stakeholder group id",
            "stakeholder_group_id",
            "group id",
            "group_id",
            default=_first(
                result,
                "stakeholder group id",
                "stakeholder_group_id",
                "group id",
                "group_id",
            ),
        ),
    )
    if group_id in (None, "", "Not recorded"):
        group_name = _first(
            inputs,
            "stakeholder group",
            "stakeholder_group",
            "group name",
            "group_name",
            default=_first(
                result,
                "stakeholder group",
                "stakeholder_group",
                "group name",
                "group_name",
            ),
        )
        return str(group_name) if group_name not in (None, "") else "Not recorded"
    return _group_label(group_id, lookups)


def _participant_displacement_counts(
    result: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> dict[int, int]:
    """Return packaged or deterministically reconstructed rank-displacement counts."""
    summary = _analysis_summary_metrics(result)
    distribution = _mapping(
        _first(summary, "effect distribution", "effect_distribution", default={})
    )
    packaged = _mapping(
        _first(
            distribution,
            "session maximum rank displacement counts",
            "session_maximum_rank_displacement_counts",
            default={},
        )
    )

    counts: dict[int, int] = {}
    for displacement, count in packaged.items():
        displacement_num = _int(displacement)
        count_num = _int(count)
        if displacement_num is not None and count_num is not None:
            counts[displacement_num] = counts.get(displacement_num, 0) + count_num

    if counts:
        return counts

    # Older packages may omit the distribution while still carrying evaluable case metrics.
    for case in cases:
        metrics = _case_metrics(case)
        displacement = _int(
            _first(metrics, "maximum rank displacement", "maximum_rank_displacement")
        )
        if displacement is not None:
            counts[displacement] = counts.get(displacement, 0) + 1
    return counts


def _redact_participant_identifiers(value: Any) -> Any:
    """Remove participant identifiers from recursive appendix data while preserving structure."""
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("_", " ")
            is_identifier_flag = normalized == "participant identifiers included"
            is_participant_identifier = (
                "participant" in normalized
                and (" id" in normalized or normalized.endswith("id") or "identifier" in normalized)
                and not is_identifier_flag
            )
            cleaned[key] = (
                "Omitted from shared audit report"
                if is_participant_identifier
                else _redact_participant_identifiers(item)
            )
        return cleaned
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_participant_identifiers(item) for item in value]
    return value


def _render_participant_influence_analysis(
    result: Mapping[str, Any],
    lookups: ReportLookups,
) -> str:
    """Render leave-one-participant-out influence as a first-class audit subsection."""
    summary = _analysis_summary_metrics(result)
    cases = _analysis_cases(result)
    identifiers_included = _participant_identifiers_included(result)

    case_count = _int(_first(summary, "case count", "case_count"))
    if case_count is None:
        case_count = len(cases)

    evaluated_count = _int(_first(summary, "evaluated count", "evaluated_count"))
    if evaluated_count is None:
        evaluated_count = sum(
            1
            for case in cases
            if str(_first(case, "status", default="")).lower() == "evaluated"
            or bool(_case_metrics(case))
        )

    not_evaluable_count = _int(
        _first(summary, "not evaluable count", "not_evaluable_count")
    )
    if not_evaluable_count is None:
        not_evaluable_count = max(case_count - evaluated_count, 0)

    max_displacement = _int(
        _first(summary, "maximum rank displacement", "maximum_rank_displacement")
    )
    strict_reversals = _int(
        _first(summary, "strict reversal count", "strict_reversal_count")
    )
    top_set_changes = _int(
        _first(summary, "top set change count", "top_set_change_count")
    )

    group_displacements: list[int] = []
    group_strict_reversals = 0
    group_top_set_changes = 0
    warning_case_count = 0
    for case in cases:
        group_metrics, _, _ = _participant_group_effect(case)
        displacement = _int(
            _first(
                group_metrics,
                "maximum rank displacement",
                "maximum_rank_displacement",
            )
        )
        if displacement is not None:
            group_displacements.append(displacement)
        group_strict_reversals += (
            _int(_first(group_metrics, "strict reversals", "strict_reversals")) or 0
        )
        group_top_set_changes += int(
            bool(_first(group_metrics, "top set changed", "top_set_changed", default=False))
        )
        if _sequence(_first(case, "warnings", default=[])):
            warning_case_count += 1

    max_group_displacement = max(group_displacements) if group_displacements else None

    cards = _metric_cards(
        [
            ("Participant cases", _fmt_number(case_count, 0), "Leave-one-participant-out cases"),
            ("Evaluated", _fmt_number(evaluated_count, 0), None),
            ("Not evaluable", _fmt_number(not_evaluable_count, 0), None),
            (
                "Maximum rank displacement",
                _fmt_number(max_displacement, 0),
                "Largest recorded session-rank movement",
            ),
            ("Strict reversals", _fmt_number(strict_reversals, 0), None),
            ("Top-set changes", _fmt_number(top_set_changes, 0), None),
            (
                "Maximum group displacement",
                _fmt_number(max_group_displacement, 0),
                "Derived from packaged participant cases",
            ),
            (
                "Group strict reversals",
                _fmt_number(group_strict_reversals, 0),
                "Derived from stakeholder-group effects",
            ),
            (
                "Group top-set changes",
                _fmt_number(group_top_set_changes, 0),
                "Derived from stakeholder-group effects",
            ),
            (
                "Cases with warnings",
                _fmt_number(warning_case_count, 0),
                "Case-level warning count",
            ),
        ]
    )

    availability = _definition_grid(
        [
            ("Method", _humanize(_first(summary, "method", default=_first(result, "method")))),
            ("Analysis run ID", _code(_first(result, "analysis run id", "analysis_run_id"))),
            (
                "Participant identifiers included",
                _fmt_bool(identifiers_included),
            ),
            (
                "Case-level evidence available",
                _fmt_bool(bool(cases)),
            ),
            (
                "Instability detected",
                _fmt_bool(_first(summary, "instability detected", "instability_detected")),
            ),
            (
                "Schema version",
                _first(
                    _mapping(_first(result, "summary", default={})),
                    "schema version",
                    "schema_version",
                    default=_first(result, "schema version", "schema_version"),
                ),
            ),
        ]
    )

    parts = [cards, _subsection("Analysis Availability", availability)]

    if cases:
        case_rows: list[list[Any]] = []
        for index, case in enumerate(cases, start=1):
            session_metrics = _case_metrics(case)
            group_metrics, group_ranking, _ = _participant_group_effect(case)
            warnings = _sequence(_first(case, "warnings", default=[]))
            case_rows.append(
                [
                    _participant_case_label(case, index),
                    _participant_case_group(case, lookups),
                    _status_badge(_first(case, "status")),
                    _case_winner(case, lookups),
                    _fmt_decimal(_first(session_metrics, "spearman"), 3),
                    _fmt_decimal(
                        _first(session_metrics, "kendall tau b", "kendall_tau_b"), 3
                    ),
                    _fmt_number(
                        _first(
                            session_metrics,
                            "maximum rank displacement",
                            "maximum_rank_displacement",
                        ),
                        0,
                    ),
                    _fmt_bool(
                        _first(
                            session_metrics,
                            "top choice retained",
                            "top_choice_retained",
                        )
                    ),
                    _winner_from_ranking(group_ranking, lookups),
                    _fmt_decimal(_first(group_metrics, "spearman"), 3),
                    _fmt_number(
                        _first(
                            group_metrics,
                            "maximum rank displacement",
                            "maximum_rank_displacement",
                        ),
                        0,
                    ),
                    _fmt_bool(
                        _first(
                            group_metrics,
                            "top choice retained",
                            "top_choice_retained",
                        )
                    ),
                    "; ".join(str(w) for w in warnings) if warnings else "None",
                ]
            )

        parts.append(
            _subsection(
                "Participant Removal Cases",
                render_table(
                    [
                        "Case",
                        "Stakeholder group",
                        "Status",
                        "Session winner",
                        "Session Spearman",
                        "Session Kendall τ-b",
                        "Session max displacement",
                        "Session top retained",
                        "Group winner",
                        "Group Spearman",
                        "Group max displacement",
                        "Group top retained",
                        "Warnings",
                    ],
                    case_rows,
                    caption=(
                        "Each row records both the session-level and stakeholder-group effect "
                        "of removing one participant. Participant identifiers are not displayed "
                        "in the shared audit report."
                    ),
                ),
                intro=(
                    "Session metrics measure change in the final collective ranking; group metrics "
                    "measure change inside the omitted participant's stakeholder group."
                ),
            )
        )
    else:
        parts.append(
            _subsection(
                "Participant Removal Cases",
                '<div class="audit-note">'
                '<strong>Case-level evidence is not included in this package.</strong>'
                '<p>The participant-influence summary is still reported above. '
                'No participant-level effect rows are reconstructed or inferred when the packaged '
                'analysis omits them.</p>'
                '</div>',
            )
        )

    displacement_counts = _participant_displacement_counts(result, cases)
    if displacement_counts:
        distribution_rows = [
            (f"Displacement {displacement}", float(count))
            for displacement, count in sorted(displacement_counts.items())
        ]
        distribution_table = render_table(
            ["Maximum rank displacement", "Cases"],
            [
                [_fmt_number(displacement, 0), _fmt_number(count, 0)]
                for displacement, count in sorted(displacement_counts.items())
            ],
            caption="Distribution of maximum session-rank displacement across evaluable participant-removal cases.",
        )
        parts.append(
            _subsection(
                "Session Rank-Displacement Distribution",
                _horizontal_bar_chart(
                    distribution_rows,
                    value_formatter=lambda v: _fmt_number(v, 0),
                )
                + distribution_table,
                intro="This visualization reports recorded case counts only; it does not add an interpretation of participant influence.",
            )
        )

    return _subsection(
        "Participant Influence",
        "".join(parts),
        intro=(
            "Leave-one-participant-out robustness results showing how the deterministic session "
            "ranking changes when one participant is omitted. Participant identifiers are withheld "
            "from this shared audit view; case sequence and stakeholder group are used when available."
        ),
    )


def _render_analyses(analyses: dict, lookups: ReportLookups) -> str:
    results = [_mapping(row) for row in _sequence(_first(analyses, "selected results", "selected_results", default=[]))]
    by_method = {str(_first(row, "method", default="")): row for row in results}

    parts = [
        _subsection("Analysis Coverage", _render_analysis_coverage(analyses)),
        _subsection(
            "Analysis Summary",
            _render_analysis_overview(results),
            intro="Summary fields are rendered directly from the deterministic analysis outputs; no narrative interpretation is added.",
        ),
    ]

    if result := by_method.get("one_at_a_time_weight_perturbation"):
        parts.append(_render_weight_perturbation_analysis(result, lookups))
    if result := by_method.get("criterion_removal"):
        parts.append(_render_criterion_removal_analysis(result, lookups))
    if result := by_method.get("rank_reversal"):
        parts.append(_render_rank_reversal_analysis(result, lookups))
    if result := by_method.get("stakeholder_group_influence"):
        parts.append(_render_influence_analysis("Stakeholder Group Influence", result, lookups))
    if result := by_method.get("participant_influence"):
        parts.append(_render_participant_influence_analysis(result, lookups))

    return section(
        "analyses",
        "7. Sensitivity & Robustness Testing",
        "".join(parts),
        intro="Deterministic robustness tests are presented as recorded metrics and reranking outcomes. Detailed case evidence is available in Appendix B.",
    )


def _render_provenance(report: SharedReport, provenance: dict) -> str:
    source_analysis_run_ids = _sequence(
        _first(provenance, "source analysis run ids", "source_analysis_run_ids", default=[])
    )
    evidence_refs = _sequence(getattr(report.revision, "evidence_refs", ()))

    main = _definition_grid(
        [
            ("Package run ID", _code(report.package_run_id)),
            ("Package hash", _code(report.package_hash, css_class="hash")),
            ("Release ID", _code(report.release_id) if report.release_id else "Not released"),
            ("Revision number", report.revision.number),
            ("Revision ID", _code(getattr(report.revision, "revision_id", None))),
            ("Source processing run ID", _code(_first(provenance, "source processing run id", "source_processing_run_id"))),
            ("Source ranking run ID", _code(_first(provenance, "source ranking run id", "source_ranking_run_id"))),
            ("Source roster hash", _code(_first(provenance, "source roster hash", "source_roster_hash"), css_class="hash")),
            ("Lineage state", _status_badge(_first(provenance, "lineage state at packaging", "lineage_state_at_packaging"))),
            ("Provenance schema version", _first(provenance, "schema version", "schema_version")),
        ]
    )

    analysis_runs = render_table(
        ["Analysis run ID"],
        [[_code(run_id)] for run_id in source_analysis_run_ids],
    )

    documents = []
    for doc in report.documents:
        documents.append(
            [
                getattr(doc, "title", "Not recorded"),
                getattr(doc, "number", "Not recorded"),
                getattr(doc, "source_reference", "Not recorded"),
                _code(getattr(doc, "content_hash", None), css_class="hash"),
            ]
        )

    body = (
        _subsection("Package and Lineage", main)
        + _subsection("Source Analysis Runs", analysis_runs)
        + _subsection(
            "Revision Evidence References",
            _html(_unordered_list(evidence_refs)),
        )
        + _subsection(
            "Source Documents",
            render_table(["Document", "Version", "Source reference", "SHA-256"], documents),
        )
    )
    return section(
        "provenance",
        "8. Provenance & Reproducibility",
        body,
        intro="Identifiers and hashes used to trace this report back to the fixed processing, ranking, analysis, roster, and source-document evidence.",
    )


def _render_pairwise_matrix(record: Mapping[str, Any], lookups: ReportLookups) -> str:
    criterion_ids = [str(v) for v in _sequence(_first(record, "criterion ids", "criterion_ids", default=[]))]
    matrix = _mapping(_first(record, "matrix", default={}))
    values = _sequence(_first(matrix, "values", default=[]))
    if not criterion_ids or not values:
        return '<p class="empty-state">No pairwise matrix recorded.</p>'

    headers = ["Criterion"] + [_criterion_label(cid, lookups) for cid in criterion_ids]
    rows = []
    for index, raw_row in enumerate(values):
        row_values = _sequence(raw_row)
        criterion_name = _criterion_label(criterion_ids[index], lookups) if index < len(criterion_ids) else f"Row {index + 1}"
        rows.append([criterion_name] + [_fmt_decimal(value, 6) for value in row_values])

    diagnostics = _mapping(_first(record, "diagnostics", default={}))
    meta = _definition_grid(
        [
            ("Scope", _weighting_scope_label(record, lookups)),
            ("Method", _humanize(_first(diagnostics, "method"))),
            ("Provider", _first(diagnostics, "provider")),
            ("Consistency ratio", _fmt_decimal(_first(diagnostics, "consistency ratio", "consistency_ratio"), 6)),
            ("Matrix hash", _code(_first(record, "matrix hash", "matrix_hash"), css_class="hash")),
        ]
    )
    return meta + render_table(headers, rows, css_class="matrix-table")



def _named_alternative_set(values: Any, lookups: ReportLookups) -> _SafeHtml:
    ids = _sequence(values)
    if not ids:
        return _safe_html('<span class="muted">None recorded</span>')
    return _safe_html(
        '<ul class="compact-list">'
        + ''.join(
            f'<li>{escape(_alternative_label(value, lookups))}</li>' for value in ids
        )
        + '</ul>'
    )


def _participant_effect_summary_cards(
    metrics: Mapping[str, Any],
    ranking: Sequence[Mapping[str, Any]],
    lookups: ReportLookups,
) -> str:
    """Compact effect summary for rapid review before exact evidence tables."""
    return _metric_cards(
        [
            (
                'Resulting winner',
                _winner_from_ranking(ranking, lookups),
                None,
            ),
            (
                'Maximum rank displacement',
                _fmt_number(
                    _first(
                        metrics,
                        'maximum rank displacement',
                        'maximum_rank_displacement',
                    ),
                    0,
                ),
                None,
            ),
            (
                'Strict reversals',
                _fmt_number(_first(metrics, 'strict reversals', 'strict_reversals'), 0),
                None,
            ),
            (
                'Top choice retained',
                _fmt_bool(
                    _first(metrics, 'top choice retained', 'top_choice_retained')
                ),
                None,
            ),
            (
                'Spearman',
                _fmt_decimal(_first(metrics, 'spearman'), 3),
                None,
            ),
            (
                'Kendall τ-b',
                _fmt_decimal(_first(metrics, 'kendall tau b', 'kendall_tau_b'), 3),
                None,
            ),
        ]
    )


def _participant_comparison_details(
    metrics: Mapping[str, Any],
    lookups: ReportLookups,
) -> str:
    """Render exact before/after comparison fields separately from headline metrics."""
    rows = [
        (
            'Baseline top set',
            _named_alternative_set(
                _first(metrics, 'baseline top set', 'baseline_top_set', default=[]),
                lookups,
            ),
        ),
        (
            'Candidate top set',
            _named_alternative_set(
                _first(metrics, 'candidate top set', 'candidate_top_set', default=[]),
                lookups,
            ),
        ),
        (
            'Baseline score margin',
            _fmt_decimal(
                _first(metrics, 'baseline score margin', 'baseline_score_margin'), 6
            ),
        ),
        (
            'Candidate score margin',
            _fmt_decimal(
                _first(metrics, 'candidate score margin', 'candidate_score_margin'), 6
            ),
        ),
        (
            'Top set changed',
            _fmt_bool(_first(metrics, 'top set changed', 'top_set_changed')),
        ),
        (
            'Tie transitions',
            _fmt_number(_first(metrics, 'tie transitions', 'tie_transitions'), 0),
        ),
        ('Top K', _fmt_number(_first(metrics, 'top k', 'top_k'), 0)),
        (
            'Top-K retention',
            _fmt_fraction_percent(
                _first(metrics, 'top k retention', 'top_k_retention')
            ),
        ),
    ]
    return _definition_grid(rows)


def _participant_affected_pairs(
    metrics: Mapping[str, Any],
    lookups: ReportLookups,
) -> str:
    pairs = [_mapping(row) for row in _sequence(
        _first(metrics, 'affected pairs', 'affected_pairs', default=[])
    )]
    if not pairs:
        return '<p class="empty-state">No affected alternative pairs recorded.</p>'
    rows = []
    for pair in pairs:
        rows.append(
            [
                _alternative_label(_first(pair, 'left'), lookups),
                _alternative_label(_first(pair, 'right'), lookups),
                _humanize(_first(pair, 'change')),
            ]
        )
    return render_table(
        ['Left alternative', 'Right alternative', 'Recorded change'],
        rows,
    )


def _participant_weighting_diagnostics_block(
    diagnostics: Mapping[str, Any],
) -> str:
    if not diagnostics:
        return '<p class="empty-state">No weighting diagnostics recorded.</p>'
    return _definition_grid(
        [
            ('Method', _humanize(_first(diagnostics, 'method'))),
            ('Provider', _first(diagnostics, 'provider')),
            (
                'Weight derivation',
                _humanize(
                    _first(diagnostics, 'weight derivation', 'weight_derivation')
                ),
            ),
            (
                'Consistency ratio',
                _fmt_decimal(
                    _first(diagnostics, 'consistency ratio', 'consistency_ratio'), 6
                ),
            ),
            (
                'Consistency threshold',
                _fmt_decimal(
                    _first(
                        diagnostics,
                        'consistency threshold',
                        'consistency_threshold',
                    ),
                    4,
                ),
            ),
            (
                'Threshold exceeded',
                _fmt_bool(
                    _first(diagnostics, 'threshold exceeded', 'threshold_exceeded')
                ),
            ),
        ]
    )


def _participant_effect_block(
    *,
    title: str,
    level_label: str,
    intro: str,
    metrics: Mapping[str, Any],
    ranking: Sequence[Mapping[str, Any]],
    diagnostics: Mapping[str, Any],
    lookups: ReportLookups,
) -> str:
    """Render one clearly bounded participant-influence effect scope."""
    if not metrics and not ranking and not diagnostics:
        body = '<p class="empty-state">No effect evidence recorded for this scope.</p>'
    else:
        body = ''.join(
            [
                _participant_effect_summary_cards(metrics, ranking, lookups),
                '<div class="case-subsection"><h5>Comparison details</h5>',
                _participant_comparison_details(metrics, lookups),
                '</div>',
                '<div class="case-subsection"><h5>Resulting ranking</h5>',
                _render_ranking_rows(ranking, lookups),
                '</div>',
                '<div class="case-subsection"><h5>Weighting diagnostics</h5>',
                _participant_weighting_diagnostics_block(diagnostics),
                '</div>',
                '<details class="case-secondary-detail">',
                '<summary>Affected alternative pairs</summary>',
                '<div class="detail-body">',
                _participant_affected_pairs(metrics, lookups),
                '</div></details>',
            ]
        )
    return (
        '<section class="participant-effect-block">'
        '<div class="participant-effect-heading">'
        f'<div><div class="effect-level">{escape(level_label)}</div>'
        f'<h4>{escape(title)}</h4></div>'
        '</div>'
        f'<p class="effect-intro">{escape(intro)}</p>'
        f'{body}'
        '</section>'
    )


def _participant_case_context(
    case: Mapping[str, Any],
    input_for_display: Any,
    warnings: Sequence[Any],
    lookups: ReportLookups,
) -> str:
    """Render privacy-safe counterfactual context separately from analysis effects."""
    inputs = _mapping(input_for_display)
    group_id = _first(
        inputs,
        'stakeholder group id',
        'stakeholder_group_id',
        default=_first(case, 'scope id', 'scope_id'),
    )
    group_name = _participant_case_group(case, lookups)
    required_groups = _sequence(
        _first(inputs, 'required group keys', 'required_group_keys', default=[])
    )
    context = _definition_grid(
        [
            ('Participant case', _participant_case_label(case, _int(_first(case, 'sequence')) or 1)),
            ('Stakeholder group', group_name),
            ('Status', _status_badge(_first(case, 'status'))),
            (
                'Warnings',
                '; '.join(str(item) for item in warnings) if warnings else 'None',
            ),
            ('Group key', _code(_first(inputs, 'group key', 'group_key'), css_class='short-code')),
            ('Stakeholder group ID', _code(group_id)),
        ]
    )
    required = (
        '<div class="case-subsection"><h5>Required stakeholder groups</h5>'
        + _unordered_list(required_groups)
        + '</div>'
        if required_groups
        else ''
    )
    return context + required


def _participant_case_provenance(case: Mapping[str, Any]) -> str:
    rows: list[tuple[str, Any]] = [
        (
            'Projected case hash',
            _code(_first(case, 'content hash', 'content_hash'), css_class='hash'),
        ),
    ]
    source_hash = _first(case, 'source content hash', 'source_content_hash')
    if source_hash not in (None, ''):
        rows.append(('Source analysis-case hash', _code(source_hash, css_class='hash')))
    projection_version = _first(
        case, 'projection schema version', 'projection_schema_version'
    )
    if projection_version not in (None, ''):
        rows.append(('Projection schema version', projection_version))
    return _definition_grid(rows)


def _render_participant_analysis_case(
    case: Mapping[str, Any],
    lookups: ReportLookups,
) -> str:
    """Purpose-built Appendix B renderer for participant influence cases."""
    inputs = _redact_participant_identifiers(_first(case, 'input', default={}))
    warnings = _sequence(_first(case, 'warnings', default=[]))
    result = _mapping(_first(case, 'result', default={}))

    session_metrics = _case_metrics(case)
    session_ranking = _case_ranking(case)
    session_diagnostics = _participant_session_weighting_diagnostics(case)
    group_metrics, group_ranking, group_diagnostics = _participant_group_effect(case)

    known_result_keys = {
        'metrics',
        'ranking',
        'weighting_diagnostics',
        'primary_effect_scope',
        'stakeholder_group_effect',
        'session_metrics',
        'session_ranking',
        'session_weighting_diagnostics',
        'group_metrics',
        'group_ranking',
        'group_weighting_diagnostics',
        'additional',
    }
    additional = dict(_mapping(_first(result, 'additional', default={})))
    for key, value in result.items():
        if key not in known_result_keys:
            additional.setdefault(key, value)
    additional = _redact_participant_identifiers(additional)

    blocks = [
        '<div class="participant-case-layout">',
        '<section class="participant-case-section participant-context">',
        '<div class="case-section-heading"><span class="case-section-number">1</span>'
        '<div><div class="case-section-kicker">Counterfactual case</div>'
        '<h4>Case Context</h4></div></div>',
        '<p class="case-section-intro">Identifies the stakeholder group associated with the omitted participant without exposing participant identity.</p>',
        _participant_case_context(case, inputs, warnings, lookups),
        '</section>',
        '<section class="participant-case-section">',
        '<div class="case-section-heading"><span class="case-section-number">2</span>'
        '<div><div class="case-section-kicker">Collective outcome</div>'
        '<h4>Session-Level Effect</h4></div></div>',
        _participant_effect_block(
            title='Effect on final session ranking',
            level_label='PRIMARY EFFECT SCOPE',
            intro='Compares the original session result with the counterfactual result after omitting this participant.',
            metrics=session_metrics,
            ranking=session_ranking,
            diagnostics=session_diagnostics,
            lookups=lookups,
        ),
        '</section>',
        '<section class="participant-case-section">',
        '<div class="case-section-heading"><span class="case-section-number">3</span>'
        '<div><div class="case-section-kicker">Within-group outcome</div>'
        '<h4>Stakeholder-Group Effect</h4></div></div>',
        _participant_effect_block(
            title='Effect within the participant stakeholder group',
            level_label='SECONDARY EFFECT SCOPE',
            intro='Shows how the same omission changes the participant stakeholder group before session-level aggregation.',
            metrics=group_metrics,
            ranking=group_ranking,
            diagnostics=group_diagnostics,
            lookups=lookups,
        ),
        '</section>',
        '<section class="participant-case-section participant-provenance">',
        '<div class="case-section-heading"><span class="case-section-number">4</span>'
        '<div><div class="case-section-kicker">Traceability</div>'
        '<h4>Audit &amp; Provenance</h4></div></div>',
        '<p class="case-section-intro">Links this privacy-safe case projection back to its deterministic source evidence.</p>',
        _participant_case_provenance(case),
        '</section>',
    ]
    if additional:
        blocks.extend(
            [
                '<details class="case-secondary-detail participant-additional">',
                '<summary>Additional deterministic fields</summary>',
                '<div class="detail-body">',
                _render_json_object(additional),
                '</div></details>',
            ]
        )
    blocks.append('</div>')
    return ''.join(blocks)


def _render_analysis_case(case: Mapping[str, Any], lookups: ReportLookups) -> str:
    """Render one detailed Appendix B analysis case."""
    is_participant_case = _first(case, "subject type", "subject_type") == "participant"
    if is_participant_case:
        return _render_participant_analysis_case(case, lookups)

    inputs = _first(case, "input", default={})
    metrics = _case_metrics(case)
    ranking_rows = _case_ranking(case)
    warnings = _sequence(_first(case, "warnings", default=[]))

    metadata = _definition_grid(
        [
            ("Sequence", _first(case, "sequence")),
            ("Status", _status_badge(_first(case, "status"))),
            ("Scope", _scope_label(case, lookups)),
            ("Subject", _subject_label(case, lookups)),
            (
                "Content hash",
                _code(_first(case, "content hash", "content_hash"), css_class="hash"),
            ),
            ("Warnings", "; ".join(str(w) for w in warnings) if warnings else "None"),
        ]
    )
    return (
        metadata
        + '<h5>Input</h5>'
        + _render_raw_value(inputs)
        + '<h5>Metrics</h5>'
        + _render_raw_value(metrics)
        + (
            '<h5>Resulting ranking</h5>'
            + _render_ranking_rows(ranking_rows, lookups)
            if ranking_rows
            else ""
        )
    )


def _render_appendices(
    *,
    context: dict,
    configuration: dict,
    validation: dict,
    weighting: dict,
    ranking: dict,
    analyses: dict,
    provenance: dict,
    lookups: ReportLookups,
) -> str:
    weighting_records = [
        _mapping(row)
        for row in _sequence(
            _first(weighting, "aggregate matrices", "aggregate_matrices", default=[])
        )
    ]
    matrix_blocks = []
    for index, record in enumerate(weighting_records, start=1):
        label = _weighting_scope_label(record, lookups)
        matrix_blocks.append(
            '<details class="appendix-detail">'
            f'<summary>{escape(str(index))}. {escape(label)}</summary>'
            f'<div class="detail-body">{_render_pairwise_matrix(record, lookups)}</div>'
            "</details>"
        )
    appendix_a = section(
        "appendix-matrices",
        "Appendix A. Pairwise Matrices",
        "".join(matrix_blocks) or '<p class="empty-state">No matrices recorded.</p>',
        intro="Exact pairwise matrices and their associated weighting diagnostics.",
    )

    analysis_results = [
        _mapping(row)
        for row in _sequence(
            _first(analyses, "selected results", "selected_results", default=[])
        )
    ]
    analysis_blocks = []
    for result in analysis_results:
        method = str(_first(result, "method", default="Unidentified analysis"))
        case_blocks = []
        for case in _analysis_cases(result):
            sequence = _first(case, "sequence", default="?")
            is_participant = _first(case, "subject type", "subject_type") == "participant"
            if is_participant:
                group = _participant_case_group(case, lookups)
                status = _humanize(_first(case, "status", default="Not recorded"))
                summary = (
                    '<span class="case-summary-title">'
                    f'Participant case {escape(str(sequence))}'
                    '</span>'
                    '<span class="case-summary-meta">'
                    f'{escape(group)} · {escape(status)} · Leave-one-participant-out'
                    '</span>'
                )
            else:
                subject = _subject_label(case, lookups)
                scope = _scope_label(case, lookups)
                summary = (
                    f'Case {escape(str(sequence))} · '
                    f'{escape(scope)} · {escape(subject)}'
                )
            case_blocks.append(
                '<details class="case-detail participant-case-detail">'
                f'<summary>{summary}</summary>'
                f'<div class="detail-body">{_render_analysis_case(case, lookups)}</div>'
                "</details>"
            )
        analysis_blocks.append(
            '<div class="appendix-method">'
            f'<h3>{escape(_humanize(method))}</h3>'
            + ("".join(case_blocks) or '<p class="empty-state">No cases recorded.</p>')
            + "</div>"
        )
    appendix_b = section(
        "appendix-analysis-cases",
        "Appendix B. Detailed Analysis Cases",
        "".join(analysis_blocks)
        or '<p class="empty-state">No analysis cases recorded.</p>',
        intro=(
            "Case-level deterministic inputs, metrics, rerankings, diagnostics, hashes, "
            "status values, and warnings. Participant Influence cases use a dedicated "
            "four-part layout separating session and stakeholder-group effects."
        ),
    )

    # A single JSON object is easier to inspect, copy, diff, and validate than the
    # recursive HTML table/definition-list view. Participant identifiers remain
    # redacted before serialization.
    raw_evidence = {
        "01_context": context,
        "02_configuration": configuration,
        "03_validation": validation,
        "04_weighting": weighting,
        "05_ranking": ranking,
        "06_analyses": _redact_participant_identifiers(analyses),
        "07_provenance": provenance,
    }
    appendix_c_body = (
        '<div class="audit-note">'
        '<strong>JSON display</strong>'
        '<p>This is a pretty-printed HTML projection of the packaged evidence. '
        'It is generated with Python\'s standard-library json module; no third-party '
        'JSON or syntax-highlighting library is required.</p>'
        '</div>'
        '<details class="raw-json-evidence">'
        '<summary>Raw packaged evidence JSON</summary>'
        '<div class="detail-body">'
        + _render_json_object(raw_evidence)
        + '</div></details>'
    )
    appendix_c = section(
        "appendix-raw",
        "Appendix C. Raw Evidence",
        appendix_c_body,
        intro=(
            "The complete report evidence is presented below as one JSON object so field "
            "names, nesting, arrays, and scalar values can be inspected directly."
        ),
    )

    return appendix_a + appendix_b + appendix_c


REPORT_CSS = r"""
:root {
    --text: #172b4d;
    --muted: #5f6b7a;
    --border: #d8e0e8;
    --surface: #f7f9fb;
    --surface-2: #eef2f6;
    --accent: #245ea8;
    --accent-dark: #17477f;
    --success: #1f7a4d;
    --success-bg: #e8f5ee;
    --warning: #8a5a00;
    --warning-bg: #fff4d6;
    --danger: #a12b2b;
    --danger-bg: #fdeaea;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
    margin: 0;
    color: var(--text);
    background: #fff;
    font: 15px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
main {
    width: min(1180px, calc(100% - 48px));
    margin: 0 auto;
    padding: 36px 0 90px;
}
h1, h2, h3, h4, h5 { line-height: 1.25; }
h1 { margin: 4px 0 10px; font-size: 32px; }
h2 { margin: 0; font-size: 24px; }
h3 { margin: 0 0 14px; font-size: 18px; }
h4 { margin: 12px 0 8px; font-size: 14px; }
h5 { margin: 16px 0 8px; font-size: 13px; }
p { margin: 8px 0 14px; }
.eyebrow {
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
}
.report-header {
    padding-bottom: 26px;
    border-bottom: 3px solid var(--text);
}
.header-meta, .package-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    align-items: center;
}
.report-purpose {
    max-width: 900px;
    color: var(--muted);
}
.package-strip {
    margin-top: 18px;
    padding: 10px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 12px;
}
.metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
    gap: 12px;
    margin: 22px 0;
}
.metric-card {
    min-height: 94px;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: #fff;
}
.metric-value { font-size: 22px; font-weight: 750; }
.metric-label { margin-top: 3px; color: var(--muted); font-size: 12px; }
.metric-note { margin-top: 5px; color: var(--muted); font-size: 11px; }
.badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
}
.badge-neutral { background: var(--surface-2); color: var(--text); }
.badge-success { background: var(--success-bg); color: var(--success); }
.badge-warning { background: var(--warning-bg); color: var(--warning); }
.badge-danger { background: var(--danger-bg); color: var(--danger); }
.toc {
    margin: 32px 0 18px;
    padding: 20px 24px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
}
.toc h2 { font-size: 19px; }
.toc ol { columns: 2; column-gap: 40px; padding-left: 22px; }
.toc li { margin: 6px 0; break-inside: avoid; }
a { color: var(--accent-dark); }
.report-section {
    margin: 48px 0;
    scroll-margin-top: 20px;
}
.section-heading {
    display: flex;
    gap: 16px;
    align-items: baseline;
    justify-content: space-between;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--border);
}
.back-to-top { font-size: 11px; white-space: nowrap; }
.section-intro, .subsection-intro { color: var(--muted); max-width: 920px; }
.subsection { margin: 26px 0 34px; }
.definition-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 10px;
    margin: 14px 0;
}
.definition-item {
    padding: 11px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: #fff;
}
.definition-label { color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
.definition-value { margin-top: 3px; overflow-wrap: anywhere; }
.callout-grid, .chart-pair {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
    margin: 14px 0;
}
.callout {
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--surface);
}
.callout h3 { font-size: 14px; }
.audit-note {
    margin: 12px 0;
    padding: 14px 16px;
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    border-radius: 6px;
    background: var(--surface);
}
.audit-note strong { display: block; margin-bottom: 4px; }
.audit-note p { margin: 4px 0 0; color: var(--muted); }
.table-wrap {
    width: 100%;
    overflow-x: auto;
    margin: 12px 0;
    border: 1px solid var(--border);
    border-radius: 6px;
}
table.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
}
table.data-table caption {
    padding: 9px 10px;
    text-align: left;
    color: var(--muted);
    background: var(--surface);
}
th {
    background: var(--surface-2);
    font-weight: 700;
    text-align: left;
    white-space: nowrap;
}
th, td {
    padding: 9px 10px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
}
tbody tr:last-child td { border-bottom: 0; }
tbody tr:nth-child(even) { background: #fbfcfd; }
.empty-cell, .empty-state { color: var(--muted); font-style: italic; }
code.technical-id, code.hash, code.short-code {
    font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
    font-size: 10.5px;
    color: var(--muted);
    overflow-wrap: anywhere;
    white-space: normal;
}
.figure {
    margin: 12px 0 18px;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: #fff;
}
.chart { display: block; width: 100%; height: auto; min-width: 620px; }
.chart-label, .chart-value { fill: var(--text); font-size: 12px; }
.chart-track { fill: var(--surface-2); }
.chart-bar { fill: var(--accent); }
.heat-cell, .rank-cell {
    display: block;
    min-width: 74px;
    padding: 7px 8px;
    border-radius: 4px;
    text-align: center;
}
.rank-cell small { display: block; margin-top: 2px; font-size: 10px; font-weight: 500; }
.compact-list { margin: 0; padding-left: 18px; }
.muted { color: var(--muted); }
details {
    margin: 10px 0;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: #fff;
}
summary {
    cursor: pointer;
    padding: 10px 12px;
    background: var(--surface);
    font-weight: 700;
}
.detail-body { padding: 12px; }
.raw-dl { display: grid; grid-template-columns: minmax(140px, 240px) 1fr; gap: 5px 12px; }
.raw-dl dt { font-weight: 700; color: var(--muted); }
.raw-dl dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }

.raw-list { margin: 5px 0; padding-left: 22px; }

.case-summary-title { display: block; font-weight: 750; }
.case-summary-meta {
    display: block;
    margin-top: 2px;
    color: var(--muted);
    font-size: 11px;
    font-weight: 500;
}
.participant-case-layout { display: grid; gap: 18px; }
.participant-case-section {
    padding: 18px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: #fff;
}
.participant-context,
.participant-provenance { background: var(--surface); }
.case-section-heading {
    display: flex;
    align-items: center;
    gap: 12px;
    padding-bottom: 10px;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
}
.case-section-heading h4 { margin: 0; font-size: 16px; }
.case-section-number {
    display: inline-grid;
    place-items: center;
    width: 30px;
    height: 30px;
    flex: 0 0 30px;
    border-radius: 999px;
    background: var(--accent);
    color: #fff;
    font-size: 13px;
    font-weight: 800;
}
.case-section-kicker,
.effect-level {
    color: var(--muted);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .06em;
    text-transform: uppercase;
}
.case-section-intro,
.effect-intro {
    color: var(--muted);
    max-width: 900px;
}
.participant-effect-block {
    margin-top: 14px;
    padding: 14px;
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    border-radius: 7px;
    background: #fff;
}
.participant-effect-heading h4 { margin: 2px 0 0; font-size: 14px; }
.case-subsection {
    margin: 18px 0;
    padding-top: 4px;
}
.case-subsection h5 {
    margin: 0 0 8px;
    padding-bottom: 5px;
    border-bottom: 1px solid var(--surface-2);
}
.case-secondary-detail { margin-top: 14px; }
.participant-additional { margin-top: 4px; }
.json-wrap {
    width: 100%;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: #0f1720;
}
.json-object {
    margin: 0;
    padding: 18px;
    min-width: 720px;
    color: #e6edf3;
    background: transparent;
    font: 11.5px/1.55 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
    white-space: pre;
    tab-size: 2;
}
.json-object code { font: inherit; color: inherit; }
.raw-json-evidence > summary { font-size: 13px; }

@media (max-width: 800px) {
    main { width: min(100% - 24px, 1180px); }
    .toc ol { columns: 1; }
    .callout-grid, .chart-pair { grid-template-columns: 1fr; }
    .raw-dl { grid-template-columns: 1fr; }
    .participant-case-section { padding: 12px; }
    .json-object { min-width: 640px; }
}

@media print {
    body { font-size: 9.5pt; }
    main { width: 100%; padding: 0; }
    .back-to-top { display: none; }
    .toc { break-after: page; }
    .report-section { margin: 24px 0; }
    .section-heading { break-after: avoid; }
    .metric-card, .callout, .definition-item, .figure, .participant-effect-block { break-inside: avoid; }
    tr { break-inside: avoid; }
    a { color: inherit; text-decoration: none; }
    details:not([open]) > :not(summary) { display: block !important; }
    summary { list-style: none; }
    .chart { min-width: 0; }
    .json-wrap { border: 0; }
    .json-object { min-width: 0; color: #000; background: #fff; white-space: pre-wrap; word-break: break-word; }
}
"""


def render_document(*, title: str, body: str) -> str:
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<style>{REPORT_CSS}</style>"
        "</head>"
        "<body><main>"
        f"{body}"
        "</main></body></html>"
    )


def deterministic_audit_export_html(report: SharedReport) -> bytes:
    evidence = report.evidence

    context = evidence.get("01_context", {})
    configuration = evidence.get("02_configuration", {})
    validation = evidence.get("03_validation", {})
    weighting = evidence.get("04_weighting", {})
    ranking = evidence.get("05_ranking", {})
    analyses = evidence.get("06_analyses", {})
    provenance = evidence.get("07_provenance", {})

    lookups = _build_report_lookups(
        context=context,
        configuration=configuration,
    )

    sections = [
        _render_report_header(report, context, configuration, validation),
        _render_toc(),
        _render_session_overview(context, configuration, validation),
        _render_scenario_definition(context, lookups),
        _render_configuration(configuration, lookups),
        _render_validation(validation, configuration, lookups),
        _render_weighting(weighting, lookups),
        _render_ranking(ranking, lookups),
        _render_analyses(analyses, lookups),
        _render_provenance(report, provenance),
        _render_appendices(
            context=context,
            configuration=configuration,
            validation=validation,
            weighting=weighting,
            ranking=ranking,
            analyses=analyses,
            provenance=provenance,
            lookups=lookups,
        ),
    ]

    return render_document(
        title=f"{report.title} — Data & Audit Report",
        body="".join(sections),
    ).encode("utf-8")
