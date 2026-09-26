"""One source of user-facing methodology for selection, results, and packages."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from poli_insight.domain.enum import AnalysisMethod


@dataclass(frozen=True)
class AnalysisTestDefinition:
    label: str
    purpose: str
    inputs: str
    methodology: str
    outputs: str
    interpretation: str


TEST_DEFINITIONS = {
    AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION: AnalysisTestDefinition(
        "Weight perturbation",
        "How much can a criterion weight change before the ranking changes?",
        "Saved weights and ranking, a range in percentage points, and a sampling step. The supported path uses crisp AHP weights and TOPSIS rankings.",
        "Change one criterion weight at a time, clip to 0–100%, redistribute remaining weight proportionally, and rerank at group and session levels. If the baseline assigns all weight to one criterion, distribute the residual equally and record a warning.",
        "Rank changes, top-set changes, agreement, and sampled stability bounds for each criterion.",
        "Bounds describe the evaluated grid, not exact mathematical breakpoints. A 20-percentage-point increase moves 30% to 50%; it is not a 20% relative increase.",
    ),
    AnalysisMethod.CRITERION_REMOVAL: AnalysisTestDefinition(
        "Criterion removal",
        "Does the ranking depend strongly on any one criterion?",
        "At least two criteria, saved pairwise matrices, and matching baseline rankings.",
        "Remove each criterion from the pairwise matrix, recompute AHP weights, and rerank at group and session levels.",
        "Ranking changes and agreement with the baseline for each omitted criterion.",
        "Larger changes indicate greater dependence on that criterion. Compare results within the same group or session scope.",
    ),
    AnalysisMethod.RANK_REVERSAL: AnalysisTestDefinition(
        "Rank reversal",
        "Does removing an alternative change the relative order of the remaining alternatives?",
        "At least three baseline alternatives and a saved ranking with its decision data.",
        "Remove each alternative, rerun ranking, and compare only surviving alternatives, including transitions to and from ties.",
        "Strict pair-order reversals, tie transitions, top-set changes, and agreement.",
        "A strict reversal means two surviving alternatives exchanged relative order. Rank numbers can compress after removal without a reversal.",
    ),
    AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE: AnalysisTestDefinition(
        "Stakeholder-group influence",
        "How much does omitting each group change the session ranking?",
        "Saved group matrices, configured voting allocations, and the source ranking. At least one group with positive total allocation must remain after omission.",
        "Omit each included group, normalize remaining allocations, rebuild the aggregate using the weighted geometric mean, and recompute AHP weights and the session ranking. Required groups are included in this hypothetical test.",
        "Top-ranked alternatives, rank changes, ranking agreement, and weighting diagnostics for each omitted group.",
        "Larger changes indicate greater dependence on that group's evidence. This is a hypothetical omission: normal required-group policies and the source ranking are preserved.",
    ),
    AnalysisMethod.PARTICIPANT_INFLUENCE: AnalysisTestDefinition(
        "Participant influence",
        "How much does omitting one participant change their group and the session ranking?",
        "Included participant evidence, saved group/session aggregates, and baseline rankings. Existing required-group and remaining-allocation rules apply.",
        "Omit each included participant, rebuild the affected group and session aggregates, and recompute weights and rankings. Emptying a required group remains not evaluable.",
        "Separate group and session ranking effects, with moderator-only individual evidence.",
        "Compare within the indicated scope. These are counterfactual comparisons, not causal claims about a person; identity restrictions still apply.",
    ),
}


def render_test_explanation(method: AnalysisMethod, *, expanded=False) -> None:
    definition = TEST_DEFINITIONS[method]
    st.write(definition.purpose)
    with st.expander(f"How {definition.label.lower()} works", expanded=expanded):
        for label, value in (
            ("Required inputs", definition.inputs),
            ("Methodology", definition.methodology),
            ("Outputs", definition.outputs),
            ("Interpretation", definition.interpretation),
        ):
            st.markdown(f"**{label}**")
            st.write(value)


def render_metric_guide() -> None:
    with st.expander("How to interpret analysis metrics"):
        st.markdown("""
- **Top set changed:** membership of the highest-scoring alternatives changed, including ties.
- **Maximum displacement:** largest absolute change in rank position (positions).
- **Kendall tau-b:** tie-aware ranking agreement from −1 to +1. +1 means agreement; −1 means reversed order. Undefined values are unavailable, not zero.
- **Strict reversal:** a pair of surviving alternatives exchanged relative order.
- **Tie transition:** a pair became tied or ceased to be tied.
- **Not evaluable:** no valid comparison was computed. These cases are excluded from stability denominators.
""")
