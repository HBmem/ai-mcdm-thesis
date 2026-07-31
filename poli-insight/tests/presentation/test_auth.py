from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from poli_insight.presentation.streamlit.auth import (
    AuthBackend,
    AuthConfigurationError,
    AuthenticationSettings,
    AuthorizationPolicy,
    LoginMethod,
    LoginStatus,
)
from poli_insight.presentation.streamlit.auth.adapters.development import (
    DEVELOPMENT_AUTHENTICATED_KEY,
    DevelopmentAuthAdapter,
)
from poli_insight.presentation.streamlit.auth.adapters.streamlit_oidc import (
    StreamlitOidcAuthAdapter,
)
from poli_insight.presentation.streamlit.auth.factory import (
    create_authentication_adapter,
)


class FakeUser(dict[str, object]):
    def __init__(self, *, logged_in: bool, **claims: object) -> None:
        super().__init__(claims)
        self.is_logged_in = logged_in

    def to_dict(self) -> dict[str, object]:
        return dict(self)


class FakeOidcRuntime:
    def __init__(self, user: FakeUser) -> None:
        self.user = user
        self.login_calls = 0
        self.logout_calls = 0

    def login(self) -> None:
        self.login_calls += 1

    def logout(self) -> None:
        self.logout_calls += 1


class DevelopmentAdapterTests(unittest.TestCase):
    def test_login_and_logout_use_the_same_principal_contract(self) -> None:
        state: dict[str, object] = {}
        adapter = DevelopmentAuthAdapter(
            admin_role="admin",
            session_state=state,
            password_loader=lambda: "correct-password",
        )

        self.assertEqual(adapter.login_method, LoginMethod.PASSWORD)
        self.assertFalse(adapter.current_principal().is_authenticated)
        self.assertEqual(
            adapter.login(password="wrong").status,
            LoginStatus.REJECTED,
        )
        self.assertNotIn(DEVELOPMENT_AUTHENTICATED_KEY, state)

        result = adapter.login(password="correct-password")

        self.assertTrue(result.authenticated)
        principal = adapter.current_principal()
        self.assertEqual(principal.subject, "local-development-admin")
        self.assertEqual(principal.roles, frozenset({"admin"}))
        adapter.logout()
        self.assertFalse(adapter.current_principal().is_authenticated)

    def test_missing_password_is_a_configuration_error(self) -> None:
        adapter = DevelopmentAuthAdapter(
            admin_role="admin",
            session_state={},
            password_loader=lambda: "",
        )

        with self.assertRaises(AuthConfigurationError):
            adapter.login(password="anything")


class OidcAdapterTests(unittest.TestCase):
    def test_extracts_stable_subject_and_normalized_roles(self) -> None:
        runtime = FakeOidcRuntime(
            FakeUser(
                logged_in=True,
                sub="researcher-1",
                name="Researcher One",
                roles="admin reviewer",
                groups=["policy-team", "reviewer"],
                access_token="must-not-be-retained",
            )
        )
        adapter = StreamlitOidcAuthAdapter(
            role_claim_names=("roles", "groups"),
            runtime=runtime,
        )

        principal = adapter.current_principal()

        self.assertEqual(adapter.login_method, LoginMethod.OIDC_REDIRECT)
        self.assertEqual(principal.subject, "researcher-1")
        self.assertEqual(principal.display_name, "Researcher One")
        self.assertEqual(
            principal.roles,
            frozenset({"admin", "reviewer", "policy-team"}),
        )
        self.assertFalse(hasattr(principal, "claims"))

    def test_missing_stable_subject_fails_closed(self) -> None:
        adapter = StreamlitOidcAuthAdapter(
            role_claim_names=("roles",),
            runtime=FakeOidcRuntime(
                FakeUser(logged_in=True, email="admin@example.test")
            ),
        )

        with self.assertRaises(AuthConfigurationError):
            adapter.current_principal()

    def test_login_and_logout_delegate_to_streamlit_runtime(self) -> None:
        runtime = FakeOidcRuntime(FakeUser(logged_in=False))
        adapter = StreamlitOidcAuthAdapter(
            role_claim_names=("roles",),
            runtime=runtime,
        )

        result = adapter.login()
        adapter.logout()

        self.assertEqual(result.status, LoginStatus.REDIRECT_STARTED)
        self.assertEqual(runtime.login_calls, 1)
        self.assertEqual(runtime.logout_calls, 1)


class AuthorizationPolicyTests(unittest.TestCase):
    def test_admin_policy_requires_authentication_and_role(self) -> None:
        runtime = FakeOidcRuntime(
            FakeUser(logged_in=True, sub="moderator", roles=["moderator"])
        )
        principal = StreamlitOidcAuthAdapter(
            role_claim_names=("roles",),
            runtime=runtime,
        ).current_principal()

        self.assertFalse(
            AuthorizationPolicy(admin_role="admin").can_access_admin(
                principal
            )
        )


class AuthenticationConfigurationTests(unittest.TestCase):
    def test_development_backend_is_rejected_outside_development(self) -> None:
        with self.assertRaises(AuthConfigurationError):
            AuthenticationSettings(
                backend=AuthBackend.DEVELOPMENT,
                environment="production",
            )

    def test_factory_selects_exactly_one_configured_adapter(self) -> None:
        development = create_authentication_adapter(
            AuthenticationSettings(
                backend=AuthBackend.DEVELOPMENT,
                environment="development",
            )
        )
        production = create_authentication_adapter(AuthenticationSettings())

        self.assertIsInstance(development, DevelopmentAuthAdapter)
        self.assertIsInstance(production, StreamlitOidcAuthAdapter)

    def test_original_auth_mode_remains_a_compatibility_alias(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POLI_INSIGHT_AUTH_MODE": "development",
                "POLI_INSIGHT_ENVIRONMENT": "development",
            },
            clear=True,
        ):
            settings = AuthenticationSettings.from_environment()

        self.assertEqual(settings.backend, AuthBackend.DEVELOPMENT)

    def test_auth_backend_takes_precedence_over_legacy_mode(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POLI_INSIGHT_AUTH_BACKEND": "streamlit_oidc",
                "POLI_INSIGHT_AUTH_MODE": "development",
                "POLI_INSIGHT_ENVIRONMENT": "production",
            },
            clear=True,
        ):
            settings = AuthenticationSettings.from_environment()

        self.assertEqual(settings.backend, AuthBackend.STREAMLIT_OIDC)


if __name__ == "__main__":
    unittest.main()
