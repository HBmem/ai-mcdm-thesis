"""Application-owned CSS only; native widgets are styled by config.toml.

Key prefixes are the public Streamlit container styling hook. Do not add
generated class names, DOM-position selectors, or widget-internal selectors.
"""

from __future__ import annotations

import streamlit as st


def render_theme() -> None:
    """Install shared tokens on each render, including standalone dialogs."""

    dark = st.get_option("theme.base") == "dark"
    surface = "#1B2A40" if dark else "#FFFFFF"
    muted = "#23344B" if dark else "#EAF0F5"
    border = "#44546A" if dark else "#D6DEE8"
    accent = "#5EEAD4" if dark else "#0F766E"
    st.html(
        f"""<style>
        [class*="st-key-pi_"] {{
            --pi-surface: {surface};
            --pi-muted: {muted};
            --pi-border: {border};
            --pi-accent: {accent};
            --pi-space-1: 0.25rem;
            --pi-space-2: 0.5rem;
            --pi-space-3: 0.75rem;
            --pi-space-4: 1rem;
            --pi-space-6: 1.5rem;
            --pi-space-8: 2rem;
            --pi-radius: 0.75rem;
            --pi-shadow: 0 3px 14px rgb(23 43 77 / 6%);
            min-width: 0;
        }}
        .st-key-pi_app_shell {{
            max-width: 1280px;
            margin-inline: auto;
            padding-block: var(--pi-space-2) var(--pi-space-8);
        }}
        [class*="st-key-pi_reading_"] {{
            max-width: 880px;
            margin-inline: auto;
            width: 100%;
        }}
        [class*="st-key-pi_surface_"], [class*="st-key-pi_admin_"] {{
            background: var(--pi-surface);
            border: 1px solid var(--pi-border);
            border-radius: var(--pi-radius);
            padding: var(--pi-space-6);
        }}
        [class*="st-key-pi_surface_filter_"],
        [class*="st-key-pi_admin_filter_"],
        [class*="st-key-pi_admin_configuration_"] {{
            background: var(--pi-muted);
        }}
        [class*="st-key-pi_surface_feature_"],
        [class*="st-key-pi_admin_session_card_"],
        [class*="st-key-pi_admin_workflow_navigation_"] {{
            box-shadow: var(--pi-shadow);
            border-top: 3px solid var(--pi-accent);
        }}
        [class*="st-key-pi_surface_metric_"] {{
            padding: var(--pi-space-4);
            height: 100%;
        }}
        [class*="st-key-pi_metric_"] {{
            background: var(--pi-surface);
            border-radius: var(--pi-radius);
        }}
        [class*="st-key-pi_admin_individual_"],
        [class*="st-key-pi_admin_group_aggregate_"],
        [class*="st-key-pi_admin_session_aggregate_"] {{
            border-left: 3px solid var(--pi-accent);
        }}
        [class*="st-key-pi_header_"] {{
            padding-block: var(--pi-space-2) var(--pi-space-6);
        }}
        [class*="st-key-pi_section_"] {{ padding-top: var(--pi-space-3); }}
        .st-key-pi_sidebar_brand {{
            padding-block: var(--pi-space-2) var(--pi-space-4);
            border-bottom: 1px solid var(--pi-border);
        }}
        @media (max-width: 640px) {{
            [class*="st-key-pi_surface_"], [class*="st-key-pi_admin_"] {{
                padding: var(--pi-space-4);
            }}
            [class*="st-key-pi_header_"] {{ padding-bottom: var(--pi-space-4); }}
        }}
        </style>"""
    )
