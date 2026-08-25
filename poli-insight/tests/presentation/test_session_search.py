from __future__ import annotations

import inspect
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from poli_insight.application.queries.page_queries import SessionSearchFilters
from poli_insight.presentation.streamlit.pages.admin import manage_sessions, processing

SEARCH_APP = """
import streamlit as st

from poli_insight.application.queries.page_queries import SessionScenarioOption
from poli_insight.presentation.streamlit.components.session_search import render_session_search

scenarios = (SessionScenarioOption("transit", "Transit policy"),)
first = render_session_search(key="first", scenarios=scenarios, domains=("Mobility",))
second = render_session_search(key="second", scenarios=scenarios, domains=("Mobility",))
st.session_state["search_test:first"] = first.search
st.session_state["search_test:second"] = second.search
"""


def test_search_filters_normalize_text_and_validate_date_order() -> None:
    filters = SessionSearchFilters(
        search="  transit  ",
        scenario_key=" transit ",
        domain=" Mobility ",
    )

    assert filters.search == "transit"
    assert filters.scenario_key == "transit"
    assert filters.domain == "Mobility"
    with pytest.raises(ValueError, match="cannot precede"):
        SessionSearchFilters(
            date_from=date(2026, 8, 22),
            date_to=date(2026, 8, 21),
        )


def test_multiple_search_components_keep_namespaced_state() -> None:
    app = AppTest.from_string(SEARCH_APP, default_timeout=10).run()

    assert not app.exception
    app = app.text_input[0].set_value("First query").run()
    app = app.text_input[1].set_value("Second query").run()

    assert app.session_state["search_test:first"] == "First query"
    assert app.session_state["search_test:second"] == "Second query"
    assert app.session_state["first:search"] == "First query"
    assert app.session_state["second:search"] == "Second query"


def test_search_component_has_two_real_page_consumers() -> None:
    assert "render_session_search(" in inspect.getsource(manage_sessions)
    assert "render_session_search(" in inspect.getsource(processing)
