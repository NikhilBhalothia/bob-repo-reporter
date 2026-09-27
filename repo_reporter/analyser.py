"""Analyser module — reads file content and produces plain-English module findings.

Takes the structured FileInfo objects from the scanner and, for each file that
exceeds the minimum-size threshold, derives:
  - A 2-3 sentence plain-English summary of what the file does.
  - A list of risk flags (no docs, no tests, high TODO count, very long file,
    long functions/classes).

No external LLM is used — summaries are built from deterministic heuristics
applied to the file's own source text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from repo_reporter.scanner import FileInfo, ScanResult

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
MIN_LINES_TO_ANALYSE = 20       # skip tiny files (configs, stubs, inits)
LONG_FILE_LINES      = 300      # flag files longer than this
LONG_FUNCTION_LINES  = 50       # flag individual functions/classes longer than this
HIGH_TODO_COUNT      = 5        # flag when todo_count exceeds this


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RiskFlag:
    """A single risk item attached to a module."""
    code: str           # short machine-readable key, e.g. "NO_DOCS"
    message: str        # human-readable explanation


@dataclass
class ModuleFinding:
    """Analysis result for one file."""
    path: str                           # relative path (from FileInfo)
    language: str
    line_count: int
    summary: str                        # 2-3 sentence plain-English description
    risks: List[RiskFlag] = field(default_factory=list)

    # Pass-through from FileInfo for convenience
    has_comments: bool = False
    has_tests: bool = False
    todo_count: int = 0


# ---------------------------------------------------------------------------
# Internal helpers — structural extraction
# ---------------------------------------------------------------------------

# Matches Python def / class signatures (captures name + body for length)
_PY_DEF_RE    = re.compile(r"^(\s*)(def |class )\s*(\w+)", re.MULTILINE)
# JS/TS function forms: `function foo`, `foo = function`, `foo = () =>`
_JS_FUNC_RE   = re.compile(r"^[\s]*(function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:function|\())", re.MULTILINE)
# Java/C#/Go method signatures
_JAVA_FUNC_RE = re.compile(r"^\s+(public|private|protected|static|override|func)\s+\S+\s+\w+\s*\(", re.MULTILINE)


def _split_into_blocks(source: str, lang: str) -> list[tuple[str, int]]:
    """
    Return a list of (name, line_count) for top-level functions/classes.
    Used to detect suspiciously long individual blocks.
    """
    if lang == "Python":
        pattern = _PY_DEF_RE
    elif lang in ("JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)"):
        pattern = _JS_FUNC_RE
    elif lang in ("Java", "C#", "Go", "Kotlin", "Swift"):
        pattern = _JAVA_FUNC_RE
    else:
        return []

    lines = source.splitlines()
    matches = list(pattern.finditer(source))
    if not matches:
        return []

    blocks: list[tuple[str, int]] = []
    for i, m in enumerate(matches):
        start_line = source[: m.start()].count("\n")
        end_line   = source[: matches[i + 1].start()].count("\n") if i + 1 < len(matches) else len(lines)
        name  = m.group(3) if lang == "Python" else m.group(0).strip()[:40]
        count = end_line - start_line
        blocks.append((name, count))
    return blocks


def _extract_imports(source: str, lang: str) -> list[str]:
    """Pull out imported module/package names to hint at what the file uses."""
    imports: list[str] = []
    if lang == "Python":
        for m in re.finditer(r"^(?:import|from)\s+([\w\.]+)", source, re.MULTILINE):
            top = m.group(1).split(".")[0]
            if top not in ("__future__", "typing", "dataclasses"):
                imports.append(top)
    elif lang in ("JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)"):
        for m in re.finditer(r"""(?:import|require)\s*[\({'"]([\w@/\-\.]+)""", source):
            imports.append(m.group(1).split("/")[0])
    elif lang == "Java":
        for m in re.finditer(r"^import\s+([\w\.]+)", source, re.MULTILINE):
            imports.append(m.group(1).split(".")[0])
    return list(dict.fromkeys(imports))[:8]   # deduplicate, cap at 8


def _extract_top_names(source: str, lang: str) -> list[str]:
    """Return names of top-level classes/functions defined in the file."""
    names: list[str] = []
    if lang == "Python":
        for m in re.finditer(r"^(?:class|def)\s+(\w+)", source, re.MULTILINE):
            names.append(m.group(1))
    elif lang in ("JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)"):
        for m in re.finditer(r"^(?:export\s+)?(?:class|function)\s+(\w+)", source, re.MULTILINE):
            names.append(m.group(1))
    elif lang in ("Java", "C#", "Kotlin"):
        for m in re.finditer(r"(?:class|interface|enum)\s+(\w+)", source):
            names.append(m.group(1))
    return names[:6]


def _has_docstring(source: str, lang: str) -> bool:
    """True if the file starts with a module-level docstring (Python) or a file header comment."""
    stripped = source.lstrip()
    if lang == "Python":
        return stripped.startswith('"""') or stripped.startswith("'''")
    if lang in ("JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)",
                "Java", "C", "C++", "C#", "Go", "Rust", "Kotlin", "Swift"):
        return stripped.startswith("/**") or stripped.startswith("/*!")
    if lang in ("Shell", "Ruby", "Python", "R"):
        return stripped.startswith("#!")  # shebang = intentional entry point
    return False


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(source: str, file_info: FileInfo) -> str:
    """
    Construct a 2-3 sentence plain-English summary from static signals.

    Strategy:
      1. First sentence — what the file defines (classes/functions found).
      2. Second sentence — what external things it depends on (imports).
      3. Third sentence (optional) — structural note (entry-point, config, etc.)
    """
    lang       = file_info.language
    path       = Path(file_info.path)
    name       = path.stem
    top_names  = _extract_top_names(source, lang)
    imports    = _extract_imports(source, lang)
    line_count = file_info.line_count

    sentences: list[str] = []

    # --- Sentence 1: what is defined ---
    if top_names:
        listed = ", ".join(f"`{n}`" for n in top_names[:4])
        extra  = f" (and {len(top_names) - 4} more)" if len(top_names) > 4 else ""
        kind   = "classes/functions" if len(top_names) > 1 else "class/function"
        sentences.append(f"`{name}` defines the {kind} {listed}{extra}.")
    else:
        # fallback: describe by file type / role
        role = _infer_role(path, lang, source)
        sentences.append(role)

    # --- Sentence 2: dependencies / imports ---
    if imports:
        dep_list = ", ".join(f"`{i}`" for i in imports[:5])
        extra    = f" and {len(imports) - 5} others" if len(imports) > 5 else ""
        sentences.append(f"It imports from {dep_list}{extra}.")
    elif lang in ("YAML", "TOML", "INI", "Config", "JSON"):
        sentences.append("It is a configuration or data file with no runtime imports.")

    # --- Sentence 3: structural context ---
    blocks     = _split_into_blocks(source, lang)
    long_fns   = [b for b in blocks if b[1] >= LONG_FUNCTION_LINES]
    if long_fns:
        fn_names = ", ".join(f"`{b[0]}`" for b in long_fns[:3])
        sentences.append(
            f"Contains {len(long_fns)} long block(s) ({fn_names}…) that may warrant splitting."
        )
    elif line_count > LONG_FILE_LINES:
        sentences.append(
            f"At {line_count} lines this is one of the larger files in the repo."
        )

    return "  ".join(sentences)


def _infer_role(path: Path, lang: str, source: str) -> str:
    """Fallback sentence when no top-level names are found."""
    name = path.name.lower()
    if name in ("requirements.txt", "pyproject.toml", "setup.cfg"):
        return f"`{path.name}` lists the project's Python dependencies."
    if name == "setup.py":
        return f"`setup.py` is the package installation script (setuptools)."
    if name in ("readme.md", "readme.rst", "readme.txt"):
        return f"`{path.name}` is the project's human-readable documentation entry point."
    if name in ("dockerfile",):
        return f"`Dockerfile` defines the container image build instructions."
    if lang in ("YAML", "TOML", "INI", "Config", "JSON"):
        return f"`{path.name}` is a {lang} configuration file."
    if lang == "Markdown":
        return f"`{path.name}` is a Markdown document."
    if lang in ("Shell", "PowerShell"):
        return f"`{path.name}` is a {lang} script."
    if path.stem.startswith("test_") or path.stem.endswith("_test"):
        return f"`{path.name}` is a test module."
    return f"`{path.name}` is a {lang} source file."


# ---------------------------------------------------------------------------
# Risk-flag builder
# ---------------------------------------------------------------------------

def _build_risks(source: str, file_info: FileInfo, lang: str) -> list[RiskFlag]:
    """Derive zero or more RiskFlag items for the given file."""
    risks: list[RiskFlag] = []

    if not file_info.has_comments and not _has_docstring(source, lang):
        risks.append(RiskFlag(
            code="NO_DOCS",
            message="No comments or docstrings found — behaviour is implicit.",
        ))

    if not file_info.has_tests:
        risks.append(RiskFlag(
            code="NO_TESTS",
            message="No corresponding test file detected for this module.",
        ))

    if file_info.todo_count >= HIGH_TODO_COUNT:
        risks.append(RiskFlag(
            code="HIGH_TODO",
            message=f"{file_info.todo_count} TODO/FIXME markers — significant unfinished work.",
        ))

    if file_info.line_count > LONG_FILE_LINES:
        risks.append(RiskFlag(
            code="LONG_FILE",
            message=f"File is {file_info.line_count} lines — consider splitting into smaller modules.",
        ))

    blocks    = _split_into_blocks(source, lang)
    long_fns  = [b for b in blocks if b[1] >= LONG_FUNCTION_LINES]
    if long_fns:
        names = ", ".join(b[0] for b in long_fns[:3])
        risks.append(RiskFlag(
            code="LONG_FUNCTIONS",
            message=f"Long function(s)/class(es) detected: {names} — may be hard to follow.",
        ))

    return risks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class RepoAnalyser:
    """Turns a ScanResult into a list of ModuleFinding objects."""

    def __init__(self, scan: ScanResult):
        self.scan = scan

    def analyse(self) -> list[ModuleFinding]:
        """
        Iterate over files in the scan, skip tiny ones, and return one
        ModuleFinding per significant file, sorted by path.
        """
        findings: list[ModuleFinding] = []

        for fi in self.scan.files:
            if fi.line_count < MIN_LINES_TO_ANALYSE:
                continue

            # Use the source text already cached by the scanner when available,
            # falling back to a fresh disk read only when it is absent (e.g. for
            # FileInfo objects constructed manually in tests or by older callers).
            if fi.source is not None:
                source = fi.source
            else:
                file_path = Path(self.scan.repo_path) / fi.path
                try:
                    source = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

            summary = _build_summary(source, fi)
            risks   = _build_risks(source, fi, fi.language)

            findings.append(ModuleFinding(
                path=fi.path,
                language=fi.language,
                line_count=fi.line_count,
                summary=summary,
                risks=risks,
                has_comments=fi.has_comments,
                has_tests=fi.has_tests,
                todo_count=fi.todo_count,
            ))

        return sorted(findings, key=lambda f: f.path)
