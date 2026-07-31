"""Dependencies supplied to every Streamlit page renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from poli_insight.application.queries.page_queries import PageQueries
from poli_insight.bootstrap import ApplicationContainer
from poli_insight.presentation.streamlit.auth import (
    AuthenticationAdapter,
    Principal,
)


@dataclass(frozen=True, slots=True)
class PageContext:
    container: ApplicationContainer
    queries: PageQueries
    principal: Principal
    authentication: AuthenticationAdapter
    routes: Mapping[str, Any]
