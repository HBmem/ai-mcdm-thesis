"""Chromium regression for real session processing; requires processing_app.py.

python tests/browser/processing.py --output /tmp/processing-screenshots
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def run(url: str, output: Path, *, mobile=False, review=False, accessibility=False):
    output.mkdir(parents=True, exist_ok=True)

    def audit(page, name):
        if not accessibility:
            return
        from axe_playwright_python.sync_playwright import Axe

        result = Axe().run(
            page,
            options={
                "runOnly": {
                    "type": "tag",
                    "values": ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
                }
            },
        )
        (output / f"{name}-accessibility.json").write_text(
            json.dumps(result.response, indent=2)
        )
        unexpected = []
        for violation in result.response["violations"]:
            for node in violation["nodes"]:
                target = str(node["target"])
                # Mobile toolbars can be portaled outside the dataframe; identify
                # that same native control by its accessible button name.
                native_columns_menu = False
                if (
                    violation["id"] == "aria-allowed-attr"
                    and len(node["target"]) == 1
                    and isinstance(node["target"][0], str)
                ):
                    native_columns_menu = page.locator(node["target"][0]).evaluate(
                        "element => !!element.querySelector('button[aria-label=\"Show/hide columns\"]')"
                    )
                known_native = violation["id"] == "aria-allowed-attr" and (
                    "stSidebar" in target
                    or "stDataFrame" in target
                    or native_columns_menu
                )
                if not known_native:
                    unexpected.append(
                        {
                            "rule": violation["id"],
                            "target": target,
                            "detail": node.get("failureSummary"),
                        }
                    )
        assert not unexpected, unexpected

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 390 if mobile else 1440, "height": 1000},
            is_mobile=mobile,
            has_touch=mobile,
        )
        page.set_default_timeout(30000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{url}/?case={'single-' if review else ''}{uuid4().hex}")
        validation = page.get_by_role("button", name="Begin Process", exact=True)
        expect(validation).to_be_visible(timeout=60000)
        expect(validation).to_be_disabled()
        page.get_by_text(
            "Create a new immutable validation run for the frozen roster.", exact=True
        ).click()
        expect(validation).to_be_enabled()
        page.screenshot(
            path=str(output / "01-validation.png"),
            full_page=True,
            animations="disabled",
        )
        audit(page, "validation")
        validation.focus()
        page.keyboard.press("Enter")
        weight = page.get_by_role("button", name="Begin Process", exact=True)
        expect(
            page.get_by_text("Step 3 of 6 · Weight Generation", exact=True)
        ).to_be_visible(timeout=60000)
        expect(page.get_by_text("2 of 6 steps complete", exact=True)).to_be_visible()
        expect(page.locator("#pi-workflow-current-step")).to_be_focused()
        weight.click()
        ranking = page.get_by_role("button", name="Begin Process", exact=True)
        expect(
            page.get_by_text("Step 4 of 6 · Create Ranking", exact=True)
        ).to_be_visible(timeout=60000)
        ranking.click()
        tests = page.get_by_role("button", name="Begin Process", exact=True)
        expect(
            page.get_by_text("Step 5 of 6 · Sensitivity and Robustness", exact=True)
        ).to_be_visible(timeout=60000)
        page.get_by_text("Stakeholder-group influence", exact=True).first.click()
        expect(
            page.locator('[data-testid="stExpander"]')
            .filter(
                has=page.get_by_text(
                    "How stakeholder-group influence works", exact=True
                )
            )
            .first.get_by_text("Required inputs", exact=True)
        ).to_be_visible()
        page.screenshot(
            path=str(output / "02-analysis-configuration.png"), full_page=True
        )
        if review:
            page.get_by_text("Criterion removal", exact=True).first.click()
        audit(page, "analysis-configuration")
        tests.click()
        # Screenshot the actual operation if still in progress, without slowing production.
        page.screenshot(
            path=str(output / "03-analysis-transition.png"),
            full_page=True,
            animations="disabled",
        )
        if review:
            expect(
                page.get_by_text(
                    "Some selected tests produced no evaluable cases. Review their reasons before continuing.",
                    exact=True,
                )
            ).to_be_visible(timeout=60000)
            expect(
                page.get_by_text("Step 5 of 6 · Sensitivity and Robustness", exact=True)
            ).to_be_visible()
            page.screenshot(
                path=str(output / "03-review-required.png"),
                full_page=True,
                animations="disabled",
            )
            audit(page, "review-required")
            page.get_by_role(
                "button",
                name="Continue to Package Results with successful evidence",
                exact=True,
            ).click()
        package = page.get_by_role("button", name="Begin Process", exact=True)
        expect(
            page.get_by_text("Step 6 of 6 · Package Results", exact=True)
        ).to_be_visible(timeout=60000)
        expect(page.get_by_text("5 of 6 steps complete", exact=True)).to_be_visible()
        page.get_by_role(
            "button", name="View Sensitivity and Robustness results", exact=True
        ).click()
        expect(
            page.get_by_text("Step 5 of 6 · Sensitivity and Robustness", exact=True)
        ).to_be_visible()
        page.get_by_role("tab", name="Stakeholder-group influence", exact=True).click()
        expect(
            page.get_by_text(
                "Method revision 2 · Required groups included as hypothetical omissions.",
                exact=True,
            )
        ).to_be_visible()
        if not review:
            expect(
                page.get_by_text(
                    "Maximum ranking change after each omission", exact=True
                )
            ).to_be_visible()
            page.get_by_text(
                "Maximum ranking change after each omission", exact=True
            ).scroll_into_view_if_needed()
        expect(page.locator('[data-testid="stException"]')).to_have_count(0)
        page.screenshot(
            path=str(output / "04-analysis-results.png"),
            full_page=True,
            animations="disabled",
        )
        audit(page, "analysis-results")
        # Refresh rebuilds progress from persisted evidence and preserves access to completion.
        page.reload()
        expect(
            page.get_by_text("Step 6 of 6 · Package Results", exact=True)
        ).to_be_visible(timeout=60000)
        page.get_by_text("Anonymous aggregate bundle", exact=True).click()
        expect(package).to_be_enabled()
        package.click()
        expect(
            page.get_by_text(
                "All 6 steps complete · Results package created", exact=True
            )
        ).to_be_visible(timeout=60000)
        expect(page.get_by_text("6 of 6 steps complete", exact=True)).to_be_visible()
        page.screenshot(
            path=str(output / "05-completion.png"),
            full_page=True,
            animations="disabled",
        )
        audit(page, "completion")
        page.set_viewport_size({"width": 720, "height": 1000})
        page.evaluate("document.body.style.zoom = '2'")
        assert not page.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth"
        ), "200% zoom overflows"
        page.evaluate("document.body.style.zoom = '1'")
        page.reload()
        expect(
            page.get_by_role("button", name="Open Reports & Publication", exact=True)
        ).to_be_visible(timeout=60000)
        assert not page.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth"
        ), "Page overflows viewport"
        page.get_by_role(
            "button", name="Open Reports & Publication", exact=True
        ).click()
        expect(
            page.get_by_role("heading", name="Reports & Publication", exact=True)
        ).to_be_visible()
        expect(page.locator('[data-testid="stException"]')).to_have_count(0)
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8527")
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/processing-screenshots")
    )
    parser.add_argument("--mobile", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--accessibility", action="store_true")
    args = parser.parse_args()
    run(
        args.url,
        args.output,
        mobile=args.mobile,
        review=args.review,
        accessibility=args.accessibility,
    )
    print("Processing browser regression passed")
