"""Scanner module — walks a repository and collects per-file health signals."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Directories to skip entirely
# ---------------------------------------------------------------------------
SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn",
    "node_modules",
    "venv", ".venv", "env", ".env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", "dist", "build", "*.egg-info",
    ".idea", ".vscode",
    "vendor",                          # Go / Ruby vendored deps
    "site-packages",                   # stray pip installs inside a repo
}

# ---------------------------------------------------------------------------
# Extension → language display name
# ---------------------------------------------------------------------------
EXT_TO_LANG: dict[str, str] = {
    ".py":    "Python",
    ".js":    "JavaScript",
    ".jsx":   "JavaScript (JSX)",
    ".ts":    "TypeScript",
    ".tsx":   "TypeScript (TSX)",
    ".java":  "Java",
    ".c":     "C",
    ".h":     "C (header)",
    ".cpp":   "C++",
    ".hpp":   "C++ (header)",
    ".cs":    "C#",
    ".go":    "Go",
    ".rs":    "Rust",
    ".rb":    "Ruby",
    ".php":   "PHP",
    ".swift": "Swift",
    ".kt":    "Kotlin",
    ".sh":    "Shell",
    ".bash":  "Shell",
    ".zsh":   "Shell",
    ".ps1":   "PowerShell",
    ".sql":   "SQL",
    ".html":  "HTML",
    ".htm":   "HTML",
    ".css":   "CSS",
    ".scss":  "SCSS",
    ".sass":  "Sass",
    ".yaml":  "YAML",
    ".yml":   "YAML",
    ".json":  "JSON",
    ".toml":  "TOML",
    ".ini":   "INI",
    ".cfg":   "Config",
    ".md":    "Markdown",
    ".rst":   "reStructuredText",
    ".txt":   "Text",
    ".r":     "R",
    ".R":     "R",
    ".dart":  "Dart",
    ".lua":   "Lua",
    ".ex":    "Elixir",
    ".exs":   "Elixir",
    ".hs":    "Haskell",
    ".jl":    "Julia",
}

# ---------------------------------------------------------------------------
# Comment / docstring patterns per language family
# ---------------------------------------------------------------------------
# Each value is a list of compiled regexes that match a *line* containing a
# comment or (for Python) an inline docstring indicator.

_HASH_COMMENT   = [re.compile(r"^\s*#")]
_SLASH_COMMENT  = [re.compile(r"^\s*//"), re.compile(r"^\s*/\*"), re.compile(r"^\s*\*")]
_SQL_COMMENT    = [re.compile(r"^\s*--"),  re.compile(r"^\s*/\*")]
_LUA_COMMENT    = [re.compile(r"^\s*--")]
_PY_DOCSTRING   = [re.compile(r'^\s*("""|\'\'\')'), *_HASH_COMMENT]

LANG_COMMENT_PATTERNS: dict[str, list[re.Pattern]] = {
    "Python":              _PY_DOCSTRING,
    "Ruby":                _HASH_COMMENT,
    "Shell":               _HASH_COMMENT,
    "PowerShell":          _HASH_COMMENT,
    "YAML":                _HASH_COMMENT,
    "Config":              _HASH_COMMENT,
    "INI":                 [re.compile(r"^\s*[#;]")],
    "TOML":                _HASH_COMMENT,
    "R":                   _HASH_COMMENT,
    "JavaScript":          _SLASH_COMMENT,
    "JavaScript (JSX)":    _SLASH_COMMENT,
    "TypeScript":          _SLASH_COMMENT,
    "TypeScript (TSX)":    _SLASH_COMMENT,
    "Java":                _SLASH_COMMENT,
    "C":                   _SLASH_COMMENT,
    "C (header)":          _SLASH_COMMENT,
    "C++":                 _SLASH_COMMENT,
    "C++ (header)":        _SLASH_COMMENT,
    "C#":                  _SLASH_COMMENT,
    "Go":                  _SLASH_COMMENT,
    "Rust":                _SLASH_COMMENT,
    "PHP":                 _SLASH_COMMENT,
    "Swift":               _SLASH_COMMENT,
    "Kotlin":              _SLASH_COMMENT,
    "Dart":                _SLASH_COMMENT,
    "SQL":                 _SQL_COMMENT,
    "Lua":                 _LUA_COMMENT,
    "Elixir":              [re.compile(r"^\s*#")],
    "Haskell":             [re.compile(r"^\s*--")],
    "Julia":               _HASH_COMMENT,
}

# Lines containing any of these tokens (case-insensitive) count as markers
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG|NOCOMMIT)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """Per-file scan result."""
    path: str                    # relative path from repo root
    language: str                # human-readable language name
    line_count: int              # total lines (incl. blank)
    has_comments: bool           # at least one comment/docstring line found
    todo_count: int              # number of TODO/FIXME/… markers
    has_tests: bool              # a corresponding test file heuristic match


@dataclass
class ScanResult:
    """Top-level result returned by RepoScanner.scan()."""
    repo_path: str               # resolved absolute path to the repo
    files: List[FileInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class RepoScanner:
    """Walks a repository path and collects health/onboarding signals."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> ScanResult:
        """Walk the repo and return a ScanResult with per-file FileInfo."""
        result = ScanResult(repo_path=str(self.repo_path))

        # Build the set of test-file stems upfront so the heuristic is O(1)
        test_stems = self._collect_test_stems()
        tests_dir_exists = (self.repo_path / "tests").is_dir() or \
                           (self.repo_path / "test").is_dir()

        for file_path in self._iter_source_files():
            rel = file_path.relative_to(self.repo_path)
            lang = EXT_TO_LANG.get(file_path.suffix, "Other")
            lines, has_comments, todo_count = self._analyse_file(file_path, lang)
            has_tests = self._has_test_coverage(file_path, test_stems, tests_dir_exists)

            result.files.append(FileInfo(
                path=str(rel),
                language=lang,
                line_count=lines,
                has_comments=has_comments,
                todo_count=todo_count,
                has_tests=has_tests,
            ))

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _iter_source_files(self):
        """Yield every file under the repo, skipping ignored directories."""
        for item in self.repo_path.rglob("*"):
            if item.is_file() and not self._is_skipped(item):
                yield item

    def _is_skipped(self, path: Path) -> bool:
        """Return True if the path is inside a directory we want to ignore."""
        for part in path.parts:
            if part in SKIP_DIRS or part.endswith(".egg-info"):
                return True
        return False

    def _collect_test_stems(self) -> set[str]:
        """
        Return a set of Path stems that look like test files.

        Covers:  test_foo.py  /  foo_test.py  inside any directory.
        """
        stems: set[str] = set()
        for f in self.repo_path.rglob("*.py"):
            if self._is_skipped(f):
                continue
            name = f.stem  # e.g. "test_utils" or "utils_test"
            if name.startswith("test_"):
                # test_utils → utils is the subject stem
                stems.add(name[len("test_"):])
            elif name.endswith("_test"):
                stems.add(name[: -len("_test")])
        return stems

    def _analyse_file(self, path: Path, lang: str) -> tuple[int, bool, int]:
        """
        Read *path* and return (line_count, has_comments, todo_count).

        Silently skips files that cannot be decoded as UTF-8 (binaries, etc.).
        """
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0, False, 0

        lines = text.splitlines()
        line_count = len(lines)

        patterns = LANG_COMMENT_PATTERNS.get(lang, [])
        has_comments = any(
            any(p.search(line) for p in patterns)
            for line in lines
        ) if patterns else False

        todo_count = sum(1 for line in lines if _TODO_RE.search(line))

        return line_count, has_comments, todo_count

    def _has_test_coverage(
        self,
        path: Path,
        test_stems: set[str],
        tests_dir_exists: bool,
    ) -> bool:
        """
        Heuristic: does a test appear to exist for *path*?

        True when any of:
          1. The file IS a test file (test_*.py / *_test.py).
          2. Its stem appears in test_stems (a matching test_<stem>.py found).
          3. The repo has a /tests or /test directory (broad coverage assumed).
        """
        stem = path.stem
        name = path.name

        # The file itself is a test
        if name.startswith("test_") or stem.endswith("_test"):
            return True

        # A dedicated test file for this module exists
        if stem in test_stems:
            return True

        # Broad heuristic: a tests/ directory exists in the repo
        if tests_dir_exists:
            return True

        return False
