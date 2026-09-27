"""Tests for repo_reporter.cli — covers fixes 1, 2, and 3."""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from repo_reporter.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_repo(tmp_path: Path, files: dict) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


MINIMAL_REPO = {
    "app.py": (
        "# Main application module\n"
        "def main():\n"
        "    pass\n" * 10
    ),
}


# ---------------------------------------------------------------------------
# Fix 1: Python 3.8/3.9 compatibility — Optional[str] import present
# ---------------------------------------------------------------------------

def test_cli_imports_optional():
    """cli.py must import Optional from typing (not use str | None syntax)."""
    import inspect
    import repo_reporter.cli as cli_mod
    src = inspect.getsource(cli_mod)
    assert "from typing import Optional" in src
    assert "str | None" not in src


# ---------------------------------------------------------------------------
# Fix 2: __main__.py exists and is importable
# ---------------------------------------------------------------------------

def test_main_module_exists():
    """repo_reporter.__main__ must be importable (enables python -m repo_reporter)."""
    import importlib
    mod = importlib.import_module("repo_reporter.__main__")
    assert mod is not None


def test_main_module_contains_cli_call():
    """__main__.py must invoke cli() so python -m repo_reporter actually works."""
    import inspect
    import repo_reporter.__main__ as main_mod
    src = inspect.getsource(main_mod)
    assert "cli()" in src


# ---------------------------------------------------------------------------
# Fix 3: --format md alias
# ---------------------------------------------------------------------------

def test_format_md_alias_accepted(tmp_path):
    """--format md must be accepted without error (alias for markdown)."""
    make_repo(tmp_path, MINIMAL_REPO)
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", str(tmp_path), "--format", "md"])
    assert result.exit_code == 0, result.output


def test_format_md_produces_markdown_output(tmp_path):
    """--format md must produce Markdown output (same as --format markdown)."""
    make_repo(tmp_path, MINIMAL_REPO)
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", str(tmp_path), "--format", "md"])
    assert result.exit_code == 0
    # Markdown output starts with the # heading
    assert "# " in result.output


def test_format_markdown_still_works(tmp_path):
    """Existing --format markdown must still be accepted."""
    make_repo(tmp_path, MINIMAL_REPO)
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", str(tmp_path), "--format", "markdown"])
    assert result.exit_code == 0
    assert "# " in result.output


def test_format_html_still_works(tmp_path):
    """Existing --format html must still be accepted."""
    make_repo(tmp_path, MINIMAL_REPO)
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", str(tmp_path), "--format", "html"])
    assert result.exit_code == 0
    assert "<!DOCTYPE html>" in result.output


def test_format_both_still_works(tmp_path):
    """Existing --format both must write report.md and report.html."""
    make_repo(tmp_path, MINIMAL_REPO)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "scan", str(tmp_path), "--format", "both", "--output", str(tmp_path)
    ])
    assert result.exit_code == 0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "report.html").exists()


def test_format_invalid_rejected(tmp_path):
    """An unknown --format value must be rejected by click."""
    make_repo(tmp_path, MINIMAL_REPO)
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", str(tmp_path), "--format", "pdf"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# General CLI behaviour
# ---------------------------------------------------------------------------

def test_scan_missing_path_exits_nonzero():
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "/nonexistent/path/xyz"])
    assert result.exit_code != 0


def test_scan_file_path_exits_nonzero(tmp_path):
    f = tmp_path / "single.py"
    f.write_text("x = 1\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", str(f)])
    assert result.exit_code != 0


def test_scan_output_to_file(tmp_path):
    make_repo(tmp_path, MINIMAL_REPO)
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", str(tmp_path), "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert "# " in out.read_text(encoding="utf-8")


def test_version_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
