"""Tests for dependency manifest parsing."""

import textwrap
import tomllib

import pytest

from ai_pr_audit.dep_manifest import (
    DepManifest,
    normalize_dist_name,
    parse_pyproject_toml,
    parse_requirements_txt,
)


class TestNormalizeDistName:
    def test_lowercases(self) -> None:
        assert normalize_dist_name("PyYAML") == "pyyaml"

    def test_collapses_underscores_to_dash(self) -> None:
        assert normalize_dist_name("requests_oauthlib") == "requests-oauthlib"

    def test_collapses_dots_to_dash(self) -> None:
        assert normalize_dist_name("typing.extensions") == "typing-extensions"

    def test_collapses_runs_of_separators(self) -> None:
        assert normalize_dist_name("a__b._c") == "a-b-c"

    def test_strips_leading_trailing_separator(self) -> None:
        assert normalize_dist_name("-foo-") == "foo"


class TestParsePyprojectToml:
    def test_extracts_project_name(self) -> None:
        toml = textwrap.dedent("""\
            [project]
            name = "ai-pr-audit"
        """)
        manifest = parse_pyproject_toml(toml)
        assert manifest.project_name == "ai-pr-audit"

    def test_normalises_project_name(self) -> None:
        toml = textwrap.dedent("""\
            [project]
            name = "AI_PR_Audit"
        """)
        assert parse_pyproject_toml(toml).project_name == "ai-pr-audit"

    def test_extracts_runtime_dependencies(self) -> None:
        toml = textwrap.dedent("""\
            [project]
            name = "x"
            dependencies = ["fastapi", "uvicorn"]
        """)
        manifest = parse_pyproject_toml(toml)
        assert manifest.declared == frozenset({"fastapi", "uvicorn"})

    def test_strips_version_specifiers(self) -> None:
        toml = textwrap.dedent("""\
            [project]
            name = "x"
            dependencies = ["fastapi>=0.110", "uvicorn[standard]>=0.27", "ruff==0.4.10"]
        """)
        manifest = parse_pyproject_toml(toml)
        assert manifest.declared == frozenset({"fastapi", "uvicorn", "ruff"})

    def test_includes_optional_dependencies(self) -> None:
        toml = textwrap.dedent("""\
            [project]
            name = "x"
            dependencies = ["fastapi"]

            [project.optional-dependencies]
            dev = ["pytest", "ruff"]
            docs = ["sphinx"]
        """)
        manifest = parse_pyproject_toml(toml)
        assert manifest.declared == frozenset({"fastapi", "pytest", "ruff", "sphinx"})

    def test_no_dependencies_section_yields_empty_declared(self) -> None:
        toml = textwrap.dedent("""\
            [project]
            name = "x"
        """)
        assert parse_pyproject_toml(toml).declared == frozenset()

    def test_no_project_section_yields_no_name(self) -> None:
        manifest = parse_pyproject_toml("[build-system]\nrequires = []\n")
        assert manifest.project_name is None
        assert manifest.declared == frozenset()

    def test_invalid_toml_raises(self) -> None:
        with pytest.raises(tomllib.TOMLDecodeError):
            parse_pyproject_toml("this is = not valid toml ===")


class TestParseRequirementsTxt:
    def test_extracts_simple_names(self) -> None:
        assert parse_requirements_txt("fastapi\nuvicorn\n") == frozenset({"fastapi", "uvicorn"})

    def test_strips_version_specifiers(self) -> None:
        content = "fastapi>=0.110\nuvicorn==0.27.0\nrequests~=2.31\n"
        assert parse_requirements_txt(content) == frozenset({"fastapi", "uvicorn", "requests"})

    def test_strips_extras(self) -> None:
        assert parse_requirements_txt("uvicorn[standard]>=0.27\n") == frozenset({"uvicorn"})

    def test_skips_blank_lines_and_comments(self) -> None:
        content = textwrap.dedent("""\
            # production deps
            fastapi

            # web server
            uvicorn  # ASGI server

        """)
        assert parse_requirements_txt(content) == frozenset({"fastapi", "uvicorn"})

    def test_skips_option_lines(self) -> None:
        content = textwrap.dedent("""\
            -r other.txt
            -e .
            --index-url https://pypi.org/simple
            fastapi
        """)
        assert parse_requirements_txt(content) == frozenset({"fastapi"})

    def test_normalises_names(self) -> None:
        content = "PyYAML\nrequests_oauthlib\n"
        assert parse_requirements_txt(content) == frozenset({"pyyaml", "requests-oauthlib"})

    def test_empty_returns_empty(self) -> None:
        assert parse_requirements_txt("") == frozenset()


class TestDepManifestIsDeclared:
    def _manifest(
        self, project_name: str | None = None, declared: tuple[str, ...] = ()
    ) -> DepManifest:
        return DepManifest(
            project_name=project_name,
            declared=frozenset(declared),
        )

    def test_matches_declared_dep(self) -> None:
        manifest = self._manifest(declared=("fastapi", "ruff"))
        assert manifest.is_declared("fastapi") is True

    def test_matches_after_normalisation(self) -> None:
        manifest = self._manifest(declared=("requests-oauthlib",))
        assert manifest.is_declared("requests_oauthlib") is True
        assert manifest.is_declared("Requests.OAuthLib") is True

    def test_matches_own_project_name(self) -> None:
        manifest = self._manifest(project_name="ai-pr-audit", declared=("fastapi",))
        assert manifest.is_declared("ai-pr-audit") is True
        assert manifest.is_declared("ai_pr_audit") is True

    def test_unknown_name_not_declared(self) -> None:
        manifest = self._manifest(declared=("fastapi",))
        assert manifest.is_declared("nonexistent_pkg") is False


class TestDepManifestMerge:
    def test_merge_unions_declared(self) -> None:
        a = DepManifest(project_name="x", declared=frozenset({"fastapi"}))
        merged = a.merge(frozenset({"pytest", "ruff"}))
        assert merged.declared == frozenset({"fastapi", "pytest", "ruff"})

    def test_merge_keeps_project_name(self) -> None:
        a = DepManifest(project_name="x", declared=frozenset())
        merged = a.merge(frozenset({"y"}))
        assert merged.project_name == "x"
