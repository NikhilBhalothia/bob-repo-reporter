"""Tests for repo_reporter.reporter."""

from pathlib import Path

import pytest

from repo_reporter.analyser import ModuleFinding, RiskFlag
from repo_reporter.reporter import (
    HtmlReporter,
    MarkdownReporter,
    ReportGenerator,
    _start_here_score,
)
from repo_reporter.scanner import FileInfo, ScanResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_scan(repo_path="/fake/repo", files=None):
    return ScanResult(repo_path=repo_path, files=files or [])


def make_finding(
    path="src/app.py",
    language="Python",
    line_count=50,
    summary="Does stuff.",
    risks=None,
    has_comments=True,
    has_tests=True,
    todo_count=0,
):
    return ModuleFinding(
        path=path,
        language=language,
        line_count=line_count,
        summary=summary,
        risks=risks or [],
        has_comments=has_comments,
        has_tests=has_tests,
        todo_count=todo_count,
    )


# ---------------------------------------------------------------------------
# _start_here_score
# ---------------------------------------------------------------------------

def test_start_here_score_readme_highest():
    readme = make_finding(path="README.md", language="Markdown")
    other  = make_finding(path="utils.py",  language="Python")
    assert _start_here_score(readme) > _start_here_score(other)


def test_start_here_score_entry_stems():
    main = make_finding(path="main.py")
    cli  = make_finding(path="cli.py")
    util = make_finding(path="utils.py")
    assert _start_here_score(main) > _start_here_score(util)
    assert _start_here_score(cli)  > _start_here_score(util)


# ---------------------------------------------------------------------------
# MarkdownReporter
# ---------------------------------------------------------------------------

def test_markdown_contains_repo_name():
    scan = make_scan(repo_path="/projects/my-project")
    md = MarkdownReporter(scan, []).render()
    assert "my-project" in md


def test_markdown_overview_section():
    scan = make_scan(files=[
        FileInfo("a.py", "Python", 100, True, 0, True),
        FileInfo("b.ts", "TypeScript", 50, False, 1, False),
    ])
    md = MarkdownReporter(scan, []).render()
    assert "Repository Overview" in md
    assert "Python" in md
    assert "TypeScript" in md


def test_markdown_no_risk_section_when_clean():
    scan  = make_scan()
    finding = make_finding(risks=[])
    md = MarkdownReporter(scan, [finding]).render()
    assert "No risk flags raised" in md


def test_markdown_risk_section_with_flags():
    scan    = make_scan()
    finding = make_finding(risks=[RiskFlag("NO_TESTS", "No tests found.")])
    md = MarkdownReporter(scan, [finding]).render()
    assert "NO_TESTS" in md or "No Tests" in md


def test_markdown_module_summaries_present():
    scan    = make_scan()
    finding = make_finding(summary="This module handles authentication.")
    md = MarkdownReporter(scan, [finding]).render()
    assert "This module handles authentication." in md


# ---------------------------------------------------------------------------
# HtmlReporter
# ---------------------------------------------------------------------------

def test_html_is_valid_skeleton():
    html = HtmlReporter("# Hello\n\nWorld\n", "my-repo").render()
    assert "<!DOCTYPE html>" in html
    assert "<title>" in html
    assert "my-repo" in html


def test_html_contains_body_content():
    html = HtmlReporter("# Section\n\nSome text here.\n", "repo").render()
    assert "Section" in html
    assert "Some text here." in html


def test_html_footer_present():
    html = HtmlReporter("x", "r").render()
    assert "IBM Bob" in html


# ---------------------------------------------------------------------------
# ReportGenerator — double generate() avoided (Fix 4 companion)
# ---------------------------------------------------------------------------

def test_report_generator_generate_returns_string():
    scan    = make_scan()
    gen     = ReportGenerator(scan, [])
    md      = gen.generate()
    assert isinstance(md, str)
    assert len(md) > 0


def test_report_generator_generate_html_returns_html():
    scan = make_scan()
    gen  = ReportGenerator(scan, [])
    html = gen.generate_html()
    assert "<!DOCTYPE html>" in html


def test_report_generator_write(tmp_path):
    scan = make_scan(repo_path=str(tmp_path))
    gen  = ReportGenerator(scan, [])
    written = gen.write(tmp_path, html=True)
    assert len(written) == 2
    md_file   = tmp_path / "report.md"
    html_file = tmp_path / "report.html"
    assert md_file.exists()
    assert html_file.exists()
    assert md_file.read_text(encoding="utf-8").startswith("#")
    assert "<!DOCTYPE html>" in html_file.read_text(encoding="utf-8")
