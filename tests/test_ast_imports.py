"""Tests for the AST import extractor."""

import textwrap

import pytest

from ai_pr_audit.ast_imports import ImportRef, extract_imports


def test_plain_import() -> None:
    refs = extract_imports("import requests\n")
    assert refs == [
        ImportRef(
            module="requests",
            name=None,
            line=1,
            col=0,
            is_relative=False,
            is_conditional=False,
        )
    ]


def test_import_with_alias_keeps_real_module_name() -> None:
    refs = extract_imports("import numpy as np\n")
    assert refs[0].module == "numpy"
    assert refs[0].name is None


def test_import_dotted_path_kept_intact() -> None:
    refs = extract_imports("import xml.etree.ElementTree\n")
    assert refs[0].module == "xml.etree.ElementTree"


def test_multiple_aliases_on_one_line_each_collected() -> None:
    refs = extract_imports("import os, sys, json\n")
    assert [r.module for r in refs] == ["os", "sys", "json"]


def test_from_import_splits_module_and_name() -> None:
    refs = extract_imports("from requests import get\n")
    assert refs == [
        ImportRef(
            module="requests",
            name="get",
            line=1,
            col=0,
            is_relative=False,
            is_conditional=False,
        )
    ]


def test_from_import_dotted_module_with_multiple_names() -> None:
    refs = extract_imports("from collections.abc import Iterable, Mapping\n")
    assert [(r.module, r.name) for r in refs] == [
        ("collections.abc", "Iterable"),
        ("collections.abc", "Mapping"),
    ]


def test_from_import_star_keeps_star_as_name() -> None:
    refs = extract_imports("from os import *\n")
    assert refs[0].name == "*"


def test_relative_import_marked_relative() -> None:
    src = textwrap.dedent("""\
        from . import sibling
        from ..pkg import thing
    """)
    refs = extract_imports(src)
    assert all(r.is_relative for r in refs)
    assert refs[0].module == "."
    assert refs[1].module == "..pkg"


def test_conditional_import_inside_try_except_importerror() -> None:
    src = textwrap.dedent("""\
        try:
            import polars
        except ImportError:
            import pandas
    """)
    refs = extract_imports(src)
    by_module = {r.module: r for r in refs}
    assert by_module["polars"].is_conditional is True
    assert by_module["pandas"].is_conditional is False


def test_conditional_import_with_tuple_of_exceptions_including_importerror() -> None:
    src = textwrap.dedent("""\
        try:
            import polars
        except (TypeError, ImportError):
            pass
    """)
    refs = extract_imports(src)
    assert refs[0].is_conditional is True


def test_try_except_other_exception_not_conditional() -> None:
    src = textwrap.dedent("""\
        try:
            import polars
        except ValueError:
            pass
    """)
    refs = extract_imports(src)
    assert refs[0].is_conditional is False


def test_bare_except_not_treated_as_conditional() -> None:
    src = textwrap.dedent("""\
        try:
            import polars
        except:
            pass
    """)
    refs = extract_imports(src)
    assert refs[0].is_conditional is False


def test_import_inside_function_still_detected() -> None:
    src = textwrap.dedent("""\
        def lazy():
            import heavy_module
            return heavy_module
    """)
    refs = extract_imports(src)
    assert refs[0].module == "heavy_module"


def test_line_and_col_are_node_position() -> None:
    src = "x = 1\nimport requests\n"
    refs = extract_imports(src)
    assert refs[0].line == 2
    assert refs[0].col == 0


def test_invalid_python_raises_syntax_error() -> None:
    with pytest.raises(SyntaxError):
        extract_imports("def broken(:\n")


def test_empty_source_returns_empty_list() -> None:
    assert extract_imports("") == []
