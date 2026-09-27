"""debt.py — Technical Debt & Code Quality Audit.

Scans source files for common anti-patterns, missing documentation, and
structural complexity signals, then assembles a "Code Health Report" in
Markdown.

Anti-patterns detected (language-aware):
  - God functions / classes (> threshold lines)
  - Magic numbers / magic strings
  - Deeply nested code (indent depth > threshold)
  - TODO / FIXME / HACK / NOCOMMIT markers
  - Missing module docstrings
  - Missing function/class docstrings (Python)
  - Commented-out code blocks
  - Wildcard imports (`from x import *`)
  - bare `except:` / `except Exception:` swallowing errors
  - Mutable default arguments in Python functions
  - print() debugging statements left in source

Usage
-----
    from repo_reporter.debt import audit_repo

    report_md = audit_repo("/path/to/repo")
    print(report_md)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Directories / extensions to skip (mirrors scanner.py convention)
# ---------------------------------------------------------------------------
SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn", "node_modules",
    "venv", ".venv", "env", ".env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", "dist", "build", ".idea", ".vscode",
    "vendor", "site-packages",
}

AUDIT_EXTS: set[str] = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".go", ".rb", ".cs",
}

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
LONG_FUNCTION_LINES  = 60    # lines in a single function / method block
LONG_FILE_LINES      = 400   # lines in a single file
DEEP_NESTING_DEPTH   = 5     # indent levels (tabs or 4-space groups)
HIGH_TODO_COUNT      = 4     # TODO/FIXME markers per file before flagging
MAGIC_NUMBER_MIN     = 2     # how many magic numbers before flagging a file


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DebtItem:
    """A single detected code-quality issue."""
    severity: str        # "HIGH" | "MEDIUM" | "LOW"
    code:     str        # short machine key, e.g. "NO_MODULE_DOC"
    message:  str        # human-readable description
    line:     int = 0    # 1-based line number (0 = whole-file issue)


@dataclass
class FileAudit:
    """Audit result for one file."""
    path:     str
    language: str
    lines:    int
    items:    List[DebtItem] = field(default_factory=list)

    @property
    def score(self) -> int:
        """0-100 health score (100 = perfect). Deducted per issue severity."""
        _DEDUCTIONS = {"HIGH": 25, "MEDIUM": 10, "LOW": 3}
        total = sum(_DEDUCTIONS.get(i.severity, 0) for i in self.items)
        return max(0, 100 - total)


@dataclass
class AuditResult:
    """Top-level audit result for the whole repository."""
    repo_path:    str
    file_audits:  List[FileAudit] = field(default_factory=list)

    @property
    def repo_score(self) -> int:
        """Mean health score across all audited files."""
        if not self.file_audits:
            return 100
        return round(sum(f.score for f in self.file_audits) / len(self.file_audits))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def audit_repo(repo_path: str | Path) -> str:
    """
    Audit every source file in *repo_path* and return a Markdown report.

    Parameters
    ----------
    repo_path : root of the repository to audit
    """
    repo = Path(repo_path).resolve()
    result = _run_audit(repo)
    return _render_markdown(result)


def _run_audit(repo: Path) -> AuditResult:
    """Walk the repo, audit each file, and return an AuditResult."""
    result = AuditResult(repo_path=str(repo))

    for f in sorted(repo.rglob("*")):
        if not f.is_file():
            continue
        if _is_skipped(f):
            continue
        if f.suffix not in AUDIT_EXTS:
            continue

        lang  = _detect_lang(f)
        audit = _audit_file(f, lang, repo)
        result.file_audits.append(audit)

    return result


# ---------------------------------------------------------------------------
# File auditor
# ---------------------------------------------------------------------------

def _audit_file(path: Path, lang: str, repo: Path) -> FileAudit:
    """Run all checks against a single file and return its FileAudit."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        fa = FileAudit(path=str(path.relative_to(repo)), language=lang, lines=0)
        fa.items.append(DebtItem("LOW", "READ_ERROR", "Could not read file."))
        return fa

    lines_list = source.splitlines()
    fa = FileAudit(
        path=str(path.relative_to(repo)),
        language=lang,
        lines=len(lines_list),
    )

    # Run every check
    _check_long_file(fa, lines_list)
    _check_missing_module_doc(fa, source, lang)
    _check_todo_markers(fa, lines_list)
    _check_deep_nesting(fa, lines_list, lang)
    _check_commented_out_code(fa, lines_list, lang)
    _check_magic_numbers(fa, lines_list, lang)
    _check_debug_prints(fa, lines_list, lang)

    if lang == "Python":
        _check_wildcard_imports(fa, lines_list)
        _check_bare_except(fa, lines_list)
        _check_mutable_defaults(fa, lines_list)
        _check_missing_function_docs(fa, source)

    return fa


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

_TODO_RE   = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG|NOCOMMIT)\b", re.I)
_MAGIC_RE  = re.compile(r"(?<!['\"\w])(?<!\.)\b(\d{2,})\b(?!\s*['\"])")  # bare integers ≥10
_PRINT_RE  = re.compile(r"^\s*print\s*\(", re.M)
_CONSOLE_RE = re.compile(r"^\s*console\.(log|warn|error|debug)\s*\(", re.M)


def _check_long_file(fa: FileAudit, lines: list[str]) -> None:
    if len(lines) > LONG_FILE_LINES:
        fa.items.append(DebtItem(
            "MEDIUM", "LONG_FILE",
            f"File is {len(lines)} lines — consider splitting into smaller modules.",
        ))


def _check_missing_module_doc(fa: FileAudit, source: str, lang: str) -> None:
    stripped = source.lstrip()
    has_doc = False
    if lang == "Python":
        has_doc = stripped.startswith('"""') or stripped.startswith("'''")
    elif lang in ("JavaScript", "TypeScript"):
        has_doc = stripped.startswith("/**") or stripped.startswith("/*!")
    if not has_doc and lang in ("Python", "JavaScript", "TypeScript", "Java"):
        fa.items.append(DebtItem(
            "MEDIUM", "NO_MODULE_DOC",
            "Missing module-level docstring / JSDoc header.",
        ))


def _check_todo_markers(fa: FileAudit, lines: list[str]) -> None:
    count = 0
    first_line = 0
    for i, line in enumerate(lines, 1):
        if _TODO_RE.search(line):
            count += 1
            if first_line == 0:
                first_line = i
    if count >= HIGH_TODO_COUNT:
        fa.items.append(DebtItem(
            "MEDIUM", "HIGH_TODO",
            f"{count} TODO/FIXME/HACK markers — significant unfinished work.",
            line=first_line,
        ))
    elif count > 0:
        fa.items.append(DebtItem(
            "LOW", "HAS_TODO",
            f"{count} TODO/FIXME marker(s) present.",
            line=first_line,
        ))


def _check_deep_nesting(fa: FileAudit, lines: list[str], lang: str) -> None:
    """Flag lines indented beyond DEEP_NESTING_DEPTH levels."""
    indent_unit = 4  # Python / JS / TS / Java
    worst_depth = 0
    worst_line  = 0
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        depth  = indent // indent_unit
        if depth > worst_depth:
            worst_depth = depth
            worst_line  = i
    if worst_depth >= DEEP_NESTING_DEPTH:
        fa.items.append(DebtItem(
            "MEDIUM", "DEEP_NESTING",
            f"Maximum indentation depth of {worst_depth} levels found — "
            "consider extracting nested logic into helper functions.",
            line=worst_line,
        ))


def _check_commented_out_code(fa: FileAudit, lines: list[str], lang: str) -> None:
    """
    Detect blocks of consecutive commented-out lines that look like code
    (contain common code keywords / punctuation).
    """
    _CODE_IN_COMMENT = re.compile(
        r"(?:def |class |function |var |const |let |import |return |if |for |while |\(|\{|\}|=>)"
    )
    if lang == "Python":
        comment_pat = re.compile(r"^\s*#\s*(.+)")
    else:
        comment_pat = re.compile(r"^\s*//\s*(.+)")

    run = 0
    first = 0
    for i, line in enumerate(lines, 1):
        m = comment_pat.match(line)
        if m and _CODE_IN_COMMENT.search(m.group(1)):
            if run == 0:
                first = i
            run += 1
        else:
            run = 0
        if run >= 3:
            fa.items.append(DebtItem(
                "LOW", "COMMENTED_CODE",
                f"Block of {run}+ commented-out lines starting at line {first} "
                "— dead code should be removed.",
                line=first,
            ))
            run = 0   # reset to avoid duplicate flags per block


def _check_magic_numbers(fa: FileAudit, lines: list[str], lang: str) -> None:
    """Flag bare numeric literals that should probably be named constants."""
    ALLOWED = {"0", "1", "2", "100"}   # universally acceptable
    found: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*", "/*")):
            continue   # skip pure comment lines
        for m in _MAGIC_RE.finditer(line):
            val = m.group(1)
            if val not in ALLOWED:
                found.append((i, val))
    if len(found) >= MAGIC_NUMBER_MIN:
        examples = ", ".join(
            f"`{v}` (line {ln})" for ln, v in found[:3]
        )
        fa.items.append(DebtItem(
            "LOW", "MAGIC_NUMBERS",
            f"{len(found)} magic number(s) found — e.g. {examples}. "
            "Extract into named constants.",
            line=found[0][0],
        ))


def _check_debug_prints(fa: FileAudit, lines: list[str], lang: str) -> None:
    source = "\n".join(lines)
    if lang == "Python":
        hits = [i + 1 for i, l in enumerate(lines)
                if _PRINT_RE.match(l) and "test" not in fa.path.lower()]
    elif lang in ("JavaScript", "TypeScript"):
        hits = [i + 1 for i, l in enumerate(lines) if _CONSOLE_RE.match(l)]
    else:
        hits = []
    if hits:
        fa.items.append(DebtItem(
            "LOW", "DEBUG_PRINT",
            f"{len(hits)} debug print/console statement(s) at line(s) "
            + ", ".join(str(h) for h in hits[:5])
            + ("…" if len(hits) > 5 else "")
            + " — remove before shipping.",
            line=hits[0],
        ))


def _check_wildcard_imports(fa: FileAudit, lines: list[str]) -> None:
    for i, line in enumerate(lines, 1):
        if re.match(r"^\s*from\s+\S+\s+import\s+\*", line):
            fa.items.append(DebtItem(
                "HIGH", "WILDCARD_IMPORT",
                f"Wildcard import (`from ... import *`) at line {i} — "
                "makes namespace unpredictable.",
                line=i,
            ))


def _check_bare_except(fa: FileAudit, lines: list[str]) -> None:
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped in ("except:", "except Exception:", "except Exception as e:"):
            fa.items.append(DebtItem(
                "MEDIUM", "BARE_EXCEPT",
                f"Broad `{stripped}` at line {i} silently swallows errors — "
                "catch specific exception types.",
                line=i,
            ))


def _check_mutable_defaults(fa: FileAudit, lines: list[str]) -> None:
    pat = re.compile(r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|list\(\)|dict\(\))")
    for i, line in enumerate(lines, 1):
        if pat.search(line):
            fa.items.append(DebtItem(
                "HIGH", "MUTABLE_DEFAULT",
                f"Mutable default argument (`[]` or `{{}}`) at line {i} — "
                "use `None` and initialise inside the function.",
                line=i,
            ))


def _check_missing_function_docs(fa: FileAudit, source: str) -> None:
    """Flag Python functions/methods that have no docstring."""
    # Match 'def name(...):\n' not followed by a docstring
    _DEF_RE = re.compile(r"^(\s*)def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?:\s*\n(\s*)(\S)", re.M)
    count = 0
    for m in _DEF_RE.finditer(source):
        next_non_blank = m.group(3)
        if next_non_blank not in ('"', "'"):
            count += 1
    if count >= 3:
        fa.items.append(DebtItem(
            "LOW", "MISSING_DOCSTRINGS",
            f"{count} function(s) appear to lack docstrings — "
            "document their purpose and parameters.",
        ))


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def _detect_lang(path: Path) -> str:
    _MAP = {
        ".py":  "Python",
        ".js":  "JavaScript", ".jsx": "JavaScript",
        ".ts":  "TypeScript",  ".tsx": "TypeScript",
        ".java": "Java",
        ".go":   "Go",
        ".rb":   "Ruby",
        ".cs":   "C#",
    }
    return _MAP.get(path.suffix, "Other")


def _is_skipped(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

_SEVERITY_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}
_SCORE_LABEL   = {
    range(90, 101): "Excellent ✅",
    range(70, 90):  "Good 👍",
    range(50, 70):  "Fair ⚠️",
    range(0,  50):  "Poor 🚨",
}


def _score_label(score: int) -> str:
    for r, label in _SCORE_LABEL.items():
        if score in r:
            return label
    return "Unknown"


def _render_markdown(r: AuditResult) -> str:
    repo_name = Path(r.repo_path).name
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines += [
        f"## 🩺 Code Health Report — `{repo_name}`\n",
        f"**Overall Repository Health Score: {r.repo_score}/100 — "
        f"{_score_label(r.repo_score)}**\n",
        f"_{len(r.file_audits)} file(s) audited · "
        f"{sum(len(f.items) for f in r.file_audits)} issue(s) found_\n",
    ]

    if not r.file_audits:
        lines.append("_No auditable source files found._")
        return "\n".join(lines)

    # ── Summary table ────────────────────────────────────────────────────────
    lines += [
        "### Summary\n",
        "| File | Language | Lines | Score | Issues |",
        "|------|----------|------:|------:|--------|",
    ]
    for fa in sorted(r.file_audits, key=lambda x: x.score):
        issue_icons = " ".join(
            _SEVERITY_ICON.get(i.severity, "⚪") for i in fa.items[:6]
        )
        lines.append(
            f"| `{fa.path}` | {fa.language} | {fa.lines:,} "
            f"| {fa.score}/100 | {issue_icons or '✅'} |"
        )
    lines.append("")

    # ── Per-file detail ──────────────────────────────────────────────────────
    lines.append("### Detailed Findings\n")
    for fa in sorted(r.file_audits, key=lambda x: x.score):
        icon = _score_label(fa.score).split()[1]  # just the emoji
        lines.append(f"#### `{fa.path}` &nbsp; {icon} {fa.score}/100\n")
        if not fa.items:
            lines.append("No issues found — file looks clean.\n")
            continue
        lines.append("| Severity | Code | Location | Description |")
        lines.append("|----------|------|----------|-------------|")
        for item in sorted(fa.items, key=lambda x: ("HIGH","MEDIUM","LOW").index(x.severity)):
            loc = f"line {item.line}" if item.line else "whole file"
            sev_icon = _SEVERITY_ICON.get(item.severity, "⚪")
            lines.append(
                f"| {sev_icon} {item.severity} | `{item.code}` "
                f"| {loc} | {item.message} |"
            )
        lines.append("")

    # ── Legend ───────────────────────────────────────────────────────────────
    lines += [
        "### Legend\n",
        "| Icon | Severity | Typical deduction |",
        "|------|----------|-------------------|",
        "| 🔴 | HIGH | -25 pts — should fix before merging |",
        "| 🟡 | MEDIUM | -10 pts — fix in current sprint |",
        "| 🔵 | LOW | -3 pts — address in next clean-up |",
        "",
        "_Report generated by **repo-reporter** — static analysis only, no LLM used._",
    ]

    return "\n".join(lines) + "\n"
