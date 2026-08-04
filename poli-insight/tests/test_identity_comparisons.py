from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = (
    PROJECT_ROOT / "src" / "poli_insight",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "migrations",
)


def _is_identity_singleton(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is None or node.value is True or node.value is False
    return isinstance(node, ast.Name) and node.id == "NotImplemented"


class IdentityComparisonTests(unittest.TestCase):
    def test_runtime_code_reserves_identity_comparisons_for_singletons(
        self,
    ) -> None:
        violations: list[str] = []
        paths = sorted(
            path
            for root in PYTHON_ROOTS
            for path in root.rglob("*.py")
        )
        for path in paths:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                left = node.left
                for operator, right in zip(
                    node.ops,
                    node.comparators,
                    strict=True,
                ):
                    if isinstance(operator, (ast.Is, ast.IsNot)) and not (
                        _is_identity_singleton(left)
                        or _is_identity_singleton(right)
                    ):
                        relative_path = path.relative_to(PROJECT_ROOT)
                        violations.append(f"{relative_path}:{node.lineno}")
                    left = right

        self.assertEqual(
            violations,
            [],
            "Use == or != for value objects such as enums; reserve is/is not "
            "for None, booleans, and other explicit singletons.",
        )


if __name__ == "__main__":
    unittest.main()
