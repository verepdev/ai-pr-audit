"""Smoke test — verifies the package imports and exposes its version."""

import ai_pr_audit


def test_package_imports() -> None:
    assert ai_pr_audit.__version__ == "0.0.0"
