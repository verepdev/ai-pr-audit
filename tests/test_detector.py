"""Tests for the hallucination detector."""

from ai_pr_audit.ast_imports import ImportRef
from ai_pr_audit.dep_manifest import DepManifest, normalize_dist_name
from ai_pr_audit.detector import detect_hallucinations


def _ref(
    module: str,
    *,
    name: str | None = None,
    line: int = 1,
    col: int = 0,
    is_relative: bool = False,
    is_conditional: bool = False,
) -> ImportRef:
    return ImportRef(
        module=module,
        name=name,
        line=line,
        col=col,
        is_relative=is_relative,
        is_conditional=is_conditional,
    )


def _manifest(*declared: str) -> DepManifest:
    """Build a manifest, normalising names the way `parse_pyproject_toml` does."""
    return DepManifest(
        project_name=None,
        declared=frozenset(normalize_dist_name(d) for d in declared),
    )


class TestSkippedByStrictBar:
    def test_stdlib_import_not_flagged(self) -> None:
        result = detect_hallucinations([_ref("os")], _manifest())
        assert result == []

    def test_dotted_stdlib_import_checked_at_top_level(self) -> None:
        result = detect_hallucinations([_ref("collections.abc")], _manifest())
        assert result == []

    def test_declared_dep_not_flagged(self) -> None:
        result = detect_hallucinations([_ref("fastapi")], _manifest("fastapi", "uvicorn"))
        assert result == []

    def test_dotted_declared_dep_matches_top_level(self) -> None:
        result = detect_hallucinations([_ref("requests.exceptions")], _manifest("requests"))
        assert result == []

    def test_pep503_normalised_match(self) -> None:
        # Import name `pyyaml`, declared as `PyYAML`
        result = detect_hallucinations([_ref("pyyaml")], _manifest("PyYAML"))
        assert result == []

    def test_known_alias_resolves_to_distribution(self) -> None:
        # `cv2` is the import; project declares `opencv-python`
        result = detect_hallucinations([_ref("cv2")], _manifest("opencv-python"))
        assert result == []

    def test_conditional_import_skipped(self) -> None:
        result = detect_hallucinations([_ref("polars", is_conditional=True)], _manifest())
        assert result == []

    def test_relative_import_skipped(self) -> None:
        result = detect_hallucinations([_ref(".helpers", is_relative=True)], _manifest())
        assert result == []


class TestFlagged:
    def test_undeclared_module_flagged(self) -> None:
        result = detect_hallucinations(
            [_ref("nonexistent_pkg", line=5, col=0)], _manifest("fastapi")
        )
        assert len(result) == 1
        assert result[0].module == "nonexistent_pkg"
        assert result[0].line == 5

    def test_reason_mentions_top_level_name(self) -> None:
        result = detect_hallucinations([_ref("polars")], _manifest())
        assert "polars" in result[0].reason

    def test_dotted_undeclared_flagged_with_full_module_in_output(self) -> None:
        # Even though we check top-level, we report the full dotted module
        # so the comment can show what the dev wrote.
        result = detect_hallucinations([_ref("nonexistent_pkg.submodule")], _manifest("fastapi"))
        assert len(result) == 1
        assert result[0].module == "nonexistent_pkg.submodule"

    def test_known_alias_without_matching_dist_still_flagged(self) -> None:
        # `cv2` is a known alias of `opencv-python`, but `opencv-python` isn't declared
        result = detect_hallucinations([_ref("cv2")], _manifest("fastapi"))
        assert len(result) == 1


class TestMixed:
    def test_separates_flagged_from_clean(self) -> None:
        imports = [
            _ref("os", line=1),  # stdlib
            _ref("fastapi", line=2),  # declared
            _ref("nonexistent_pkg", line=3),  # FLAG
            _ref("polars", line=4, is_conditional=True),  # conditional, skip
            _ref(".sibling", line=5, is_relative=True),  # relative, skip
            _ref("imaginary_lib", line=6),  # FLAG
        ]
        result = detect_hallucinations(imports, _manifest("fastapi"))
        assert [(h.module, h.line) for h in result] == [
            ("nonexistent_pkg", 3),
            ("imaginary_lib", 6),
        ]

    def test_preserves_input_order(self) -> None:
        imports = [
            _ref("zzz_first", line=1),
            _ref("aaa_second", line=2),
        ]
        result = detect_hallucinations(imports, _manifest())
        assert [h.module for h in result] == ["zzz_first", "aaa_second"]

    def test_empty_input_returns_empty(self) -> None:
        assert detect_hallucinations([], _manifest("fastapi")) == []


class TestProjectOwnNameTreatedAsDeclared:
    def test_own_package_recognised(self) -> None:
        manifest = DepManifest(
            project_name="ai-pr-audit",
            declared=frozenset({"fastapi"}),
        )
        # `import ai_pr_audit` from within the project should not be flagged
        result = detect_hallucinations([_ref("ai_pr_audit")], manifest)
        assert result == []
