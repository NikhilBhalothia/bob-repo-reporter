"""Tests for repo_reporter.analyser."""

import textwrap
from pathlib import Path

import pytest

from repo_reporter.analyser import (
    MIN_LINES_TO_ANALYSE,
    RepoAnalyser,
    _build_risks,
    _build_summary,
    _extract_imports,
    _extract_top_names,
    _has_docstring,
)
from repo_reporter.scanner import FileInfo, ScanResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_file_info(
    path="mod.py",
    language="Python",
    line_count=30,
    has_comments=True,
    todo_count=0,
    has_tests=True,
    source=None,
) -> FileInfo:
    return FileInfo(
        path=path,
        language=language,
        line_count=line_count,
        has_comments=has_comments,
        todo_count=todo_count,
        has_tests=has_tests,
        source=source,
    )


def make_scan_result(repo_path: str, files=None) -> ScanResult:
    return ScanResult(repo_path=repo_path, files=files or [])


# ---------------------------------------------------------------------------
# _extract_top_names
# ---------------------------------------------------------------------------

def test_extract_top_names_python():
    src = "class Foo:\n    pass\n\ndef bar():\n    pass\n"
    names = _extract_top_names(src, "Python")
    assert "Foo" in names
    assert "bar" in names


def test_extract_top_names_returns_empty_for_unknown_lang():
    src = "fn main() {}\n"
    names = _extract_top_names(src, "Rust")
    assert names == []


# ---------------------------------------------------------------------------
# _extract_imports
# ---------------------------------------------------------------------------

def test_extract_imports_python():
    src = "import os\nimport sys\nfrom pathlib import Path\n"
    imports = _extract_imports(src, "Python")
    assert "os" in imports
    assert "sys" in imports
    assert "pathlib" in imports


def test_extract_imports_filters_typing_futures():
    src = "from __future__ import annotations\nfrom typing import List\nimport click\n"
    imports = _extract_imports(src, "Python")
    assert "__future__" not in imports
    assert "typing" not in imports
    assert "click" in imports


# ---------------------------------------------------------------------------
# _has_docstring
# ---------------------------------------------------------------------------

def test_has_docstring_python_triple_quote():
    assert _has_docstring('"""Module docstring."""\nx = 1\n', "Python") is True


def test_has_docstring_python_no_docstring():
    assert _has_docstring("x = 1\n", "Python") is False


def test_has_docstring_js_jsdoc():
    assert _has_docstring("/** @module foo */\nconst x = 1;\n", "JavaScript") is True


def test_has_docstring_js_no_jsdoc():
    assert _has_docstring("const x = 1;\n", "JavaScript") is False


# ---------------------------------------------------------------------------
# _build_risks
# ---------------------------------------------------------------------------

def test_build_risks_no_docs():
    fi = make_file_info(has_comments=False, has_tests=True)
    src = "x = 1\n"  # no docstring, no comments
    risks = _build_risks(src, fi, "Python")
    codes = [r.code for r in risks]
    assert "NO_DOCS" in codes


def test_build_risks_no_tests():
    fi = make_file_info(has_tests=False, has_comments=True)
    src = "# comment\nx = 1\n"
    risks = _build_risks(src, fi, "Python")
    assert any(r.code == "NO_TESTS" for r in risks)


def test_build_risks_high_todo():
    fi = make_file_info(todo_count=6, has_tests=True)
    src = "# some source\n"
    risks = _build_risks(src, fi, "Python")
    assert any(r.code == "HIGH_TODO" for r in risks)


def test_build_risks_clean_file():
    fi = make_file_info(has_comments=True, has_tests=True, todo_count=0, line_count=25)
    src = '"""Docstring."""\nx = 1\n'
    risks = _build_risks(src, fi, "Python")
    assert risks == []


# ---------------------------------------------------------------------------
# RepoAnalyser.analyse() — Fix 4: uses cached source, no second read
# ---------------------------------------------------------------------------

def test_analyser_uses_cached_source(tmp_path):
    """When FileInfo.source is populated the analyser must NOT read from disk."""
    # Build source that is definitely >= MIN_LINES_TO_ANALYSE lines
    src = textwrap.dedent("""\
        \"\"\"A well-documented module.\"\"\"

        def hello():
            pass
    """) * 6  # 6 × 4 lines = 24 lines, safely above MIN_LINES_TO_ANALYSE (20)

    fi = make_file_info(
        path="nofile.py",          # path does NOT exist on disk
        line_count=len(src.splitlines()),
        has_comments=True,
        has_tests=True,
        source=src,
    )
    scan = make_scan_result(repo_path=str(tmp_path), files=[fi])
    findings = RepoAnalyser(scan).analyse()
    assert len(findings) == 1
    assert "hello" in findings[0].summary


def test_analyser_skips_tiny_files(tmp_path):
    fi = make_file_info(line_count=MIN_LINES_TO_ANALYSE - 1, source="x = 1\n")
    scan = make_scan_result(repo_path=str(tmp_path), files=[fi])
    findings = RepoAnalyser(scan).analyse()
    assert findings == []


def test_analyser_sorted_by_path(tmp_path):
    files = [
        make_file_info(path="z_mod.py", source="# z\n" * 25),
        make_file_info(path="a_mod.py", source="# a\n" * 25),
    ]
    scan = make_scan_result(repo_path=str(tmp_path), files=files)
    findings = RepoAnalyser(scan).analyse()
    paths = [f.path for f in findings]
    assert paths == sorted(paths)
