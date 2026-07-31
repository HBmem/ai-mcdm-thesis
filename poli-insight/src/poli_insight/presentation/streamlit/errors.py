"""Safe, consistent error handling for Streamlit page execution."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar
from uuid import uuid4

import streamlit as st

from poli_insight.application.queries.page_queries import PageQueryError


logger = logging.getLogger(__name__)
Params = ParamSpec("Params")
ReturnT = TypeVar("ReturnT")


class UserFacingError(RuntimeError):
    """An expected failure whose message is safe to render verbatim."""

    def __init__(
        self,
        message: str,
        *,
        title: str = "Unable to complete that action",
    ) -> None:
        super().__init__(message)
        self.title = title


def page_error_boundary(
    renderer: Callable[Params, ReturnT],
) -> Callable[Params, ReturnT | None]:
    """Render safe errors while allowing Streamlit control exceptions through."""

    @wraps(renderer)
    def guarded(*args: Params.args, **kwargs: Params.kwargs) -> ReturnT | None:
        try:
            return renderer(*args, **kwargs)
        except UserFacingError as error:
            render_error(error.title, str(error))
        except PageQueryError:
            reference = _error_reference()
            logger.exception("Page query failed [%s]", reference)
            render_error(
                "Data could not be loaded",
                "Please try again. If the problem continues, share the "
                f"reference {reference} with the administrator.",
            )
        except Exception:  # noqa: BLE001 - this is the page's final boundary
            reference = _error_reference()
            logger.exception("Unhandled page failure [%s]", reference)
            render_error(
                "Something went wrong",
                "The page could not finish. Please refresh before retrying an "
                "action, or share the reference "
                f"{reference} with the administrator.",
            )
        return None

    return guarded


def render_error(title: str, message: str) -> None:
    st.error(f"**{title}**\n\n{message}", icon=":material/error:")


def render_access_denied(*, authenticated: bool) -> None:
    if authenticated:
        render_error(
            "Administrator access required",
            "Your account is signed in but does not have the required role.",
        )
    else:
        render_error(
            "Sign in required",
            "Sign in with an authorized administrator account to continue.",
        )


def render_startup_error() -> None:
    """Render a safe fatal error while called from an active exception block."""

    reference = _error_reference()
    logger.exception("Application startup failed [%s]", reference)
    render_error(
        "Poli Insight could not start",
        "Check the application configuration and database, then retry. Share "
        f"the reference {reference} with the administrator if needed.",
    )


def _error_reference() -> str:
    return uuid4().hex[:12]
