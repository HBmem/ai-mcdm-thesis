from poli_insight.presentation.streamlit.urls import (
    private_invitation_url,
    private_resume_url,
)


def test_private_resume_url_encodes_all_query_values() -> None:
    url = private_resume_url(
        "https://research.example.test/participate",
        session_slug="budget study/2026",
        access_token="token+with/slashes?and=delimiters",
    )

    assert url == (
        "https://research.example.test/participate?"
        "session=budget+study%2F2026&"
        "access=token%2Bwith%2Fslashes%3Fand%3Ddelimiters"
    )


def test_private_resume_url_appends_participation_route_to_application_root() -> None:
    url = private_resume_url(
        "http://localhost:8501",
        session_slug="test4",
        access_token="private-token",
    )

    assert url == (
        "http://localhost:8501/participate?"
        "session=test4&access=private-token"
    )


def test_private_resume_url_preserves_deployment_subpath_without_duplication() -> None:
    url = private_resume_url(
        "https://research.example.test/poli-insight/",
        session_slug="study",
        access_token="private-token",
    )
    already_routed = private_resume_url(
        "https://research.example.test/poli-insight/participate",
        session_slug="study",
        access_token="private-token",
    )

    expected = (
        "https://research.example.test/poli-insight/participate?"
        "session=study&access=private-token"
    )
    assert url == expected
    assert already_routed == expected


def test_private_invitation_url_is_complete_and_encoded() -> None:
    url = private_invitation_url(
        "https://research.example.test/poli-insight",
        session_slug="budget study/2026",
        invitation_token="invite+token/with?delimiters",
    )

    assert url == (
        "https://research.example.test/poli-insight/participate?"
        "session=budget+study%2F2026&"
        "invitation=invite%2Btoken%2Fwith%3Fdelimiters"
    )
