"""release.py — Automated Release Notes from git log.

Parses git commit history and formats it into a clean, categorised,
human-readable release notes document.

Categorisation is based on the Conventional Commits specification
(https://www.conventionalcommits.org) with sensible fallbacks for
repos that don't follow it strictly.

Usage
-----
    from repo_reporter.release import build_release_notes

    notes = build_release_notes("/path/to/repo", tag="v1.2.0", limit=50)
    print(notes)   # Markdown string
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Commit:
    """A single parsed commit."""
    sha:        str
    subject:    str
    author:     str
    date:       str      # ISO date string
    category:   str      # resolved category key
    scope:      str      # conventional-commit scope, e.g. "parser"
    breaking:   bool     # True if BREAKING CHANGE


@dataclass
class ReleaseNotes:
    """Full result for one release."""
    tag:       str
    from_ref:  str
    to_ref:    str
    date:      str
    commits:   List[Commit] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

# Each entry: (display label, conventional-commit type prefixes)
_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("✨ New Features",           ("feat", "feature", "add", "new")),
    ("🐛 Bug Fixes",              ("fix", "bug", "bugfix", "hotfix", "patch")),
    ("⚡ Performance",             ("perf", "performance", "optim")),
    ("♻️  Refactoring",             ("refactor", "refact", "rework")),
    ("🧪 Tests",                  ("test", "tests", "spec")),
    ("🔧 Build & CI",             ("build", "ci", "chore", "deps", "release")),
    ("💅 Style & Formatting",     ("style", "fmt", "format", "lint")),
    ("📚 Documentation",          ("docs", "doc", "readme", "documentation")),
    ("🔒 Security",               ("security", "sec", "auth", "cve")),
    ("🗑 Deprecations & Removals", ("deprecat", "remove", "revert")),
]

_CAT_MAP: dict[str, str] = {}   # prefix → category label
for _label, _prefixes in _CATEGORIES:
    for _p in _prefixes:
        _CAT_MAP[_p] = _label

_OTHER_CATEGORY = "🔀 Other Changes"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_release_notes(
    repo_path: str | Path,
    *,
    tag: str = "Next Release",
    limit: int = 50,
    from_ref: Optional[str] = None,    # e.g. "v1.0.0"; auto-detected if None
    to_ref: str = "HEAD",
) -> str:
    """
    Parse recent git history and return Markdown release notes.

    Parameters
    ----------
    repo_path : root of the git repository
    tag       : label for the release section header (e.g. "v2.0.0")
    limit     : max number of commits to include
    from_ref  : starting git ref (default: previous tag or first commit)
    to_ref    : ending git ref (default: HEAD)
    """
    repo = Path(repo_path).resolve()
    commits = _parse_commits(repo, limit=limit, from_ref=from_ref, to_ref=to_ref)

    if not commits:
        return f"## {tag}\n\n_No commits found in this range._\n"

    notes = ReleaseNotes(
        tag=tag,
        from_ref=from_ref or _detect_previous_tag(repo) or "initial",
        to_ref=to_ref,
        date=datetime.now().strftime("%Y-%m-%d"),
        commits=commits,
    )
    return _render_markdown(notes)


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str) -> str:
    """Run a git command; return stdout or empty string on error."""
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _detect_previous_tag(repo: Path) -> Optional[str]:
    """Return the most recent git tag before HEAD, if any."""
    out = _run_git(repo, "describe", "--tags", "--abbrev=0", "HEAD^")
    return out.strip() or None


def _parse_commits(
    repo: Path,
    *,
    limit: int,
    from_ref: Optional[str],
    to_ref: str,
) -> List[Commit]:
    """
    Run `git log` and parse each commit into a Commit dataclass.

    Format string:  <sha>|<author>|<date>|<subject>
    """
    ref_range = f"{from_ref}..{to_ref}" if from_ref else to_ref
    sep = "\x1f"  # ASCII unit-separator — safe delimiter
    fmt = f"%H{sep}%aN{sep}%ad{sep}%s"

    raw = _run_git(
        repo,
        "log",
        f"--max-count={limit}",
        f"--format={fmt}",
        "--date=short",
        "--no-merges",
        ref_range,
    )

    commits: list[Commit] = []
    for line in raw.splitlines():
        parts = line.split(sep)
        if len(parts) < 4:
            continue
        sha, author, date, subject = parts[0], parts[1], parts[2], parts[3]
        cat, scope, breaking = _classify(subject)
        commits.append(Commit(
            sha=sha[:8],
            subject=subject,
            author=author,
            date=date,
            category=cat,
            scope=scope,
            breaking=breaking,
        ))

    return commits


def _classify(subject: str) -> tuple[str, str, bool]:
    """
    Classify a commit subject into (category, scope, is_breaking_change).

    Handles:
      - `feat(parser)!: add new syntax`  → New Features, scope=parser, breaking=True
      - `fix: handle null`                → Bug Fixes, scope="", breaking=False
      - `BREAKING CHANGE: ...`            → whichever category + breaking=True
      - Plain messages without a prefix   → "Other Changes"
    """
    breaking = bool(re.search(r"BREAKING[ -]CHANGE|!:", subject, re.I))

    # Conventional commit: type(scope)!: message
    m = re.match(r"^(\w+)(?:\(([^)]+)\))?(!)?\s*:\s*(.+)", subject)
    if m:
        prefix = m.group(1).lower()
        scope  = m.group(2) or ""
        if m.group(3):
            breaking = True
        category = _CAT_MAP.get(prefix, _OTHER_CATEGORY)
        return category, scope, breaking

    # No conventional prefix — try keyword matching on the first word
    first_word = subject.split()[0].lower().rstrip(":") if subject.split() else ""
    category = _CAT_MAP.get(first_word, _OTHER_CATEGORY)
    return category, "", breaking


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def _render_markdown(notes: ReleaseNotes) -> str:
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines += [
        f"## {notes.tag}",
        f"> Released: {notes.date} &nbsp;·&nbsp; "
        f"{len(notes.commits)} commit(s) since `{notes.from_ref}`\n",
    ]

    # ── Breaking changes callout ─────────────────────────────────────────────
    breaking = [c for c in notes.commits if c.breaking]
    if breaking:
        lines.append("### ⚠️ Breaking Changes\n")
        for c in breaking:
            lines.append(f"- **{c.subject}** *(by {c.author}, {c.date})*")
        lines.append("")

    # ── Categorised sections ─────────────────────────────────────────────────
    # Preserve category order defined in _CATEGORIES
    ordered_labels = [label for label, _ in _CATEGORIES] + [_OTHER_CATEGORY]
    buckets: dict[str, list[Commit]] = {label: [] for label in ordered_labels}

    for c in notes.commits:
        buckets.setdefault(c.category, []).append(c)

    for label in ordered_labels:
        commits_in_cat = buckets.get(label, [])
        if not commits_in_cat:
            continue
        lines.append(f"### {label}\n")
        for c in commits_in_cat:
            scope_part = f"**({c.scope})** " if c.scope else ""
            lines.append(
                f"- {scope_part}`{c.subject}` "
                f"— {c.author} · `{c.sha}` · {c.date}"
            )
        lines.append("")

    # ── Stats footer ─────────────────────────────────────────────────────────
    authors = sorted({c.author for c in notes.commits})
    lines += [
        "---",
        f"**Contributors:** {', '.join(authors)}  ",
        f"**Range:** `{notes.from_ref}` → `{notes.to_ref}`  ",
        "_Release notes generated by **repo-reporter**._",
    ]

    return "\n".join(lines) + "\n"
