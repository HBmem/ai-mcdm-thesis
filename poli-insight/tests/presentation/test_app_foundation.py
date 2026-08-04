from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class AppFoundationTests(unittest.TestCase):
    def test_public_home_renders_without_exposing_an_exception(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POLI_INSIGHT_AUTH_BACKEND": "streamlit_oidc",
                "POLI_INSIGHT_ENVIRONMENT": "production",
            },
            clear=False,
        ):
            app = AppTest.from_file("app.py", default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertEqual(
            tuple(item.value for item in app.title),
            ("Poli:primary[Insight]",),
        )
        self.assertTrue(
            {"Participate", "Results", "About"}.issubset(
                {item.label for item in app.button}
            )
        )

    def test_development_admin_navigation_builds_only_when_explicit(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POLI_INSIGHT_AUTH_BACKEND": "development",
                "POLI_INSIGHT_ENVIRONMENT": "development",
            },
            clear=False,
        ):
            app = AppTest.from_file("app.py", default_timeout=10)
            app.session_state["auth:development:authenticated"] = True
            app.run()

        self.assertFalse(app.exception)
        self.assertIn("Sign out", tuple(button.label for button in app.button))


if __name__ == "__main__":
    unittest.main()
