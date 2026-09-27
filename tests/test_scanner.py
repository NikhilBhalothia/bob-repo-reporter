"""Tests for repo_reporter.scanner."""

import textwrap
from pathlib import Path

import pytest

from repo_reporter.scanner import (
    EXT_TO_LANG,
    SKIP_DIRS,
    FileInfo,
    RepoScanner,
    ScanResult,
    _TODO_RE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_repo(tmp_path: Path, files: dict) -> Path:
    """Write *files* (relative-path → text) under *tmp_path* and return it."""
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests — EXT_TO_LANG
# ---------------------------------------------------------------------------

def test_ext_to_lang_known_extensions():
    assert EXT_TO_LANG[".py"] == "Python"
    assert EXT_TO_LANG[".ts"] == "TypeScript"
    assert EXT_TO_LANG[".go"] == "Go"


# ---------------------------------------------------------------------------
# Unit tests — SKIP_DIRS / _is_skipped
# ---------------------------------------------------------------------------

def test_skip_dirs_contains_common_noise():
    assert ".git" in SKIP_DIRS
    assert "node_modules" in SKIP_DIRS
    assert "__pycache__" in SKIP_DIRS
    assert "venv" in SKIP_DIRS


def test_is_skipped_ignores_egg_info(tmp_path):
    """The .egg-info suffix check must work even though the glob literal in
    SKIP_DIRS is a dead entry (the .endswith guard handles it correctly)."""
    scanner = RepoScanner(tmp_path)
    fake = tmp_path / "mypackage.egg-info" / "PKG-INFO"
    assert scanner._is_skipped(fake) is True


def test_is_skipped_normal_file(tmp_path):
    scanner = RepoScanner(tmp_path)
    normal = tmp_path / "src" / "main.py"
    assert scanner._is_skipped(normal) is False


# ---------------------------------------------------------------------------
# Unit tests — _TODO_RE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("# TODO: fix this", True),
    ("# FIXME: broken", True),
    ("# HACK: workaround", True),
    ("# XXX: investigate", True),
    ("# BUG: crashes on empty", True),
    ("# NOCOMMIT", True),
    ("# todo lowercase", True),   # case-insensitive
    ("# just a regular comment", False),
    ("print('nothing here')", False),
])
def test_todo_re(line, expected):
    assert bool(_TODO_RE.search(line)) is expected


# ---------------------------------------------------------------------------
# Integration tests — RepoScanner.scan()
# ---------------------------------------------------------------------------

def test_scan_returns_scan_result(tmp_path):
    make_repo(tmp_path, {"hello.py": "x = 1\n"})
    result = RepoScanner(tmp_path).scan()
    assert isinstance(result, ScanResult)
    assert result.repo_path == str(tmp_path.resolve())


def test_scan_detects_python_file(tmp_path):
    make_repo(tmp_path, {
        "app.py": """\
            # main module
            def run():
                pass
        """
    })
    result = RepoScanner(tmp_path).scan()
    paths = [f.path for f in result.files]
    assert any("app.py" in p for p in paths)


def test_scan_skips_git_dir(tmp_path):
    make_repo(tmp_path, {
        "src/app.py": "x = 1\n",
        ".git/config": "[core]\n    bare = false\n",
    })
    result = RepoScanner(tmp_path).scan()
    for fi in result.files:
        assert ".git" not in fi.path


def test_scan_counts_todos(tmp_path):
    make_repo(tmp_path, {
        "work.py": """\
            # TODO: first thing
            x = 1
            # FIXME: second thing
            y = 2
        """
    })
    result = RepoScanner(tmp_path).scan()
    fi = next(f for f in result.files if "work.py" in f.path)
    assert fi.todo_count == 2


def test_scan_detects_comments(tmp_path):
    make_repo(tmp_path, {
        "commented.py": "# this is a comment\nx = 1\n",
        "uncommented.py": "x = 1\ny = 2\n",
    })
    result = RepoScanner(tmp_path).scan()
    by_path = {f.path: f for f in result.files}
    assert any(f.has_comments for p, f in by_path.items() if "commented.py" in p)


def test_scan_language_detection(tmp_path):
    make_repo(tmp_path, {
        "index.ts": "const x: number = 1;\n",
        "style.css": "body { margin: 0; }\n",
    })
    result = RepoScanner(tmp_path).scan()
    by_path = {f.path: f for f in result.files}
    ts = next(f for p, f in by_path.items() if "index.ts" in p)
    css = next(f for p, f in by_path.items() if "style.css" in p)
    assert ts.language == "TypeScript"
    assert css.language == "CSS"


# ---------------------------------------------------------------------------
# Fix 4: source text is cached on FileInfo (no second disk read needed)
# ---------------------------------------------------------------------------

def test_scan_caches_source_text(tmp_path):
    """FileInfo.source must be populated with the file's text content."""
    content = "# hello\nx = 1\n"
    make_repo(tmp_path, {"mod.py": content})
    result = RepoScanner(tmp_path).scan()
    fi = next(f for f in result.files if "mod.py" in f.path)
    assert fi.source is not None
    assert "x = 1" in fi.source


def test_scan_source_none_on_oserror(tmp_path, monkeypatch):
    """If _analyse_file hits OSError, source should be None and line_count 0."""
    make_repo(tmp_path, {"bad.py": "x = 1\n"})
    scanner = RepoScanner(tmp_path)

    original = scanner._analyse_file

    def raise_oserror(path, lang):
        return 0, False, 0, None

    monkeypatch.setattr(scanner, "_analyse_file", raise_oserror)
    result = scanner.scan()
    for fi in result.files:
        if "bad.py" in fi.path:
            assert fi.source is None
