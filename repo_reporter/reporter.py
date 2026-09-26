"""Reporter module — renders ModuleFinding list as Markdown and/or HTML."""

from __future__ import annotations

import datetime
import re
from collections import Counter
from pathlib import Path
from typing import List

from repo_reporter.scanner import ScanResult
from repo_reporter.analyser import ModuleFinding, RiskFlag

# ---------------------------------------------------------------------------
# Heuristics for "Start Here" ranking
# ---------------------------------------------------------------------------

# Stems that strongly suggest an entry-point or architectural anchor
_ENTRY_STEMS = {"main", "app", "server", "index", "cli", "manage", "__main__"}
_ENTRY_NAMES = {"setup.py", "pyproject.toml", "package.json", "go.mod", "cargo.toml"}
_DOC_NAMES   = {"readme.md", "readme.rst", "readme.txt"}

def _start_here_score(f: ModuleFinding) -> int:
    """Higher score = more important for a new developer to read first."""
    score = 0
    name  = Path(f.path).name.lower()
    stem  = Path(f.path).stem.lower()

    if name in _DOC_NAMES:
        score += 10
    if stem in _ENTRY_STEMS:
        score += 8
    if name in _ENTRY_NAMES:
        score += 7
    # Larger files tend to contain more core logic
    score += min(f.line_count // 50, 5)
    # Files with lots of defined names (imported heavily in others) rank up
    if f.has_comments:
        score += 1
    return score


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

RISK_EMOJI = {
    "NO_DOCS":        "📄",
    "NO_TESTS":       "🧪",
    "HIGH_TODO":      "📝",
    "LONG_FILE":      "📏",
    "LONG_FUNCTIONS": "🔬",
}

def _risk_icon(code: str) -> str:
    return RISK_EMOJI.get(code, "⚠️")


class MarkdownReporter:
    """Renders the full onboarding report as a Markdown string."""

    def __init__(self, scan: ScanResult, findings: List[ModuleFinding]):
        self.scan     = scan
        self.findings = findings
        self.now      = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def render(self) -> str:
        sections = [
            self._header(),
            self._overview(),
            self._start_here(),
            self._risk_summary(),
            self._per_module(),
            self._footer(),
        ]
        return "\n\n".join(s.strip() for s in sections if s.strip()) + "\n"

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def _header(self) -> str:
        repo_name = Path(self.scan.repo_path).name
        return (
            f"# 🗂 Repo Health & Onboarding Report — `{repo_name}`\n\n"
            f"> Generated {self.now} · "
            f"{len(self.scan.files)} files scanned · "
            f"{len(self.findings)} modules analysed"
        )

    def _overview(self) -> str:
        lines = ["## 📊 Repository Overview"]

        # Language breakdown
        lang_counts: Counter = Counter()
        lang_lines:  Counter = Counter()
        total_lines = 0
        for fi in self.scan.files:
            lang_counts[fi.language] += 1
            lang_lines[fi.language]  += fi.line_count
            total_lines              += fi.line_count

        lines.append(f"\n| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total files | {len(self.scan.files)} |")
        lines.append(f"| Total lines of code | {total_lines:,} |")
        lines.append(f"| Languages detected | {len(lang_counts)} |")
        lines.append(f"| Modules with risk flags | "
                     f"{sum(1 for f in self.findings if f.risks)} |")

        lines.append("\n### Languages")
        lines.append("| Language | Files | Lines |")
        lines.append("|----------|------:|------:|")
        for lang, count in lang_counts.most_common():
            lines.append(f"| {lang} | {count} | {lang_lines[lang]:,} |")

        return "\n".join(lines)

    def _start_here(self) -> str:
        lines = ["## 🚀 Start Here"]
        lines.append(
            "_These are the most important files to read first to understand "
            "the project's structure and entry points._\n"
        )

        ranked = sorted(self.findings, key=_start_here_score, reverse=True)[:5]
        if not ranked:
            lines.append("_No significant modules found._")
            return "\n".join(lines)

        for i, f in enumerate(ranked, 1):
            risks_inline = ""
            if f.risks:
                icons = " ".join(_risk_icon(r.code) for r in f.risks)
                risks_inline = f" &nbsp;{icons}"
            lines.append(f"### {i}. `{f.path}`{risks_inline}")
            lines.append(f"**{f.language}** · {f.line_count:,} lines")
            lines.append(f"\n{f.summary}")

        return "\n\n".join(lines)

    def _risk_summary(self) -> str:
        risky = [f for f in self.findings if f.risks]
        if not risky:
            return "## ✅ Risk Flags\n\n_No risk flags raised — looking healthy!_"

        lines = ["## ⚠️ Risk Flags"]
        lines.append(
            "_Files that need attention before a new developer touches them._\n"
        )

        # Group by risk code for a quick at-a-glance table
        by_code: dict[str, list[str]] = {}
        for f in risky:
            for r in f.risks:
                by_code.setdefault(r.code, []).append(f.path)

        for code, paths in sorted(by_code.items()):
            icon = _risk_icon(code)
            label = code.replace("_", " ").title()
            lines.append(f"### {icon} {label} ({len(paths)} file{'s' if len(paths) != 1 else ''})")
            for p in paths:
                lines.append(f"- `{p}`")

        return "\n\n".join(lines)

    def _per_module(self) -> str:
        if not self.findings:
            return ""

        lines = ["## 📁 Module Summaries"]
        lines.append(
            "_One entry per significant file (≥20 lines). "
            "Tiny config/init files are omitted._\n"
        )

        for f in self.findings:
            # Sub-heading
            risk_icons = " ".join(_risk_icon(r.code) for r in f.risks) if f.risks else "✅"
            lines.append(f"### `{f.path}` &nbsp; {risk_icons}")
            lines.append(
                f"**Language:** {f.language} &nbsp;|&nbsp; "
                f"**Lines:** {f.line_count:,} &nbsp;|&nbsp; "
                f"**TODOs:** {f.todo_count} &nbsp;|&nbsp; "
                f"**Tests:** {'yes' if f.has_tests else 'no'} &nbsp;|&nbsp; "
                f"**Docs:** {'yes' if f.has_comments else 'no'}"
            )
            lines.append(f"\n{f.summary}")

            if f.risks:
                lines.append("\n**Risk flags:**")
                for r in f.risks:
                    lines.append(f"- {_risk_icon(r.code)} **{r.code}** — {r.message}")

        return "\n\n".join(lines)

    def _footer(self) -> str:
        return (
            "---\n"
            "_Report generated by **repo-reporter**. "
            "Summaries are derived from static analysis — no LLM used._"
        )


# ---------------------------------------------------------------------------
# HTML renderer (wraps the Markdown output)
# ---------------------------------------------------------------------------

class HtmlReporter:
    """
    Converts the Markdown report to a self-contained HTML file.

    Uses a minimal inline CSS — no external dependencies.
    """

    def __init__(self, markdown_text: str, repo_name: str):
        self.md        = markdown_text
        self.repo_name = repo_name

    def render(self) -> str:
        body = self._md_to_html(self.md)
        return _HTML_TEMPLATE.format(
            title=f"Onboarding Report — {self.repo_name}",
            body=body,
        )

    # ------------------------------------------------------------------
    # Minimal Markdown → HTML (no external lib needed)
    # ------------------------------------------------------------------

    @staticmethod
    def _md_to_html(md: str) -> str:
        """
        Convert the specific Markdown dialect we emit to HTML.
        Handles headings, bold, inline code, tables, lists, hr, blockquote.
        """
        lines  = md.split("\n")
        out    = []
        in_table  = False
        in_list   = False

        def close_table():
            nonlocal in_table
            if in_table:
                out.append("</tbody></table>")
                in_table = False

        def close_list():
            nonlocal in_list
            if in_list:
                out.append("</ul>")
                in_list = False

        def inline(text: str) -> str:
            """Apply inline formatting."""
            # backtick code
            text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
            # bold
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            # italic
            text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            # &nbsp; pass-through (already HTML)
            return text

        i = 0
        while i < len(lines):
            raw = lines[i]
            line = raw.rstrip()

            # Horizontal rule
            if re.match(r"^---+$", line):
                close_table(); close_list()
                out.append("<hr>")
                i += 1; continue

            # Headings
            m = re.match(r"^(#{1,4})\s+(.*)", line)
            if m:
                close_table(); close_list()
                level = len(m.group(1))
                text  = inline(m.group(2))
                slug  = re.sub(r"[^\w\-]", "-", m.group(2).lower())
                out.append(f'<h{level} id="{slug}">{text}</h{level}>')
                i += 1; continue

            # Blockquote
            if line.startswith("> "):
                close_table(); close_list()
                out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
                i += 1; continue

            # Table row
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                # Skip separator rows (---|---)
                if all(re.match(r"^[-: ]+$", c) for c in cells):
                    i += 1; continue
                if not in_table:
                    out.append('<table><thead><tr>')
                    out.append("".join(f"<th>{inline(c)}</th>" for c in cells))
                    out.append("</tr></thead><tbody>")
                    in_table = True
                else:
                    out.append("<tr>")
                    out.append("".join(f"<td>{inline(c)}</td>" for c in cells))
                    out.append("</tr>")
                i += 1; continue

            close_table()

            # Unordered list
            m = re.match(r"^- (.*)", line)
            if m:
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                out.append(f"<li>{inline(m.group(1))}</li>")
                i += 1; continue

            close_list()

            # Blank line
            if not line.strip():
                out.append("")
                i += 1; continue

            # Plain paragraph
            out.append(f"<p>{inline(line)}</p>")
            i += 1

        close_table()
        close_list()
        return "\n".join(out)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.7;
    color: #1f2328;
    background: #ffffff;
    margin: 0;
    padding: 2rem 1rem;
  }}
  .wrapper {{
    max-width: 820px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 1.6rem; border-bottom: 2px solid #e5e7eb; padding-bottom: .4rem; }}
  h2 {{ font-size: 1.25rem; margin-top: 2rem; border-bottom: 1px solid #e5e7eb; padding-bottom: .3rem; }}
  h3 {{ font-size: 1rem; margin-top: 1.5rem; color: #1f2328; }}
  h4 {{ font-size: .9rem; margin-top: 1.2rem; color: #57606a; }}
  code {{
    background: #f6f8fa;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    padding: 1px 5px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: .85em;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: .75rem 0;
    font-size: .9em;
  }}
  th, td {{
    border: 1px solid #e5e7eb;
    padding: .4rem .75rem;
    text-align: left;
  }}
  th {{ background: #f7f8fa; font-weight: 600; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  ul {{ padding-left: 1.5rem; }}
  li {{ margin: .2rem 0; }}
  blockquote {{
    margin: .5rem 0;
    padding: .4rem 1rem;
    background: #f7f8fa;
    border-left: 4px solid #3b82d4;
    color: #57606a;
  }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 2rem 0; }}
  .footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid #e5e7eb;
    color: #57606a;
    font-size: .8rem;
    text-align: center;
  }}
</style>
</head>
<body>
<div class="wrapper">
{body}
<div class="footer">Made with IBM Bob</div>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public facade — used by cli.py
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Facade: renders Markdown + optionally HTML, and writes files."""

    def __init__(self, scan: ScanResult, findings: List[ModuleFinding]):
        self.scan     = scan
        self.findings = findings

    def generate(self) -> str:
        """Return the Markdown report as a string (used by CLI stdout path)."""
        return MarkdownReporter(self.scan, self.findings).render()

    def generate_html(self) -> str:
        """Return the HTML report as a string."""
        md        = self.generate()
        repo_name = Path(self.scan.repo_path).name
        return HtmlReporter(md, repo_name).render()

    def write(self, out_dir: Path, *, html: bool = True) -> list[Path]:
        """
        Write report.md (and optionally report.html) into *out_dir*.
        Returns list of paths written.
        """
        written: list[Path] = []

        md_path = out_dir / "report.md"
        md_path.write_text(self.generate(), encoding="utf-8")
        written.append(md_path)

        if html:
            html_path = out_dir / "report.html"
            html_path.write_text(self.generate_html(), encoding="utf-8")
            written.append(html_path)

        return written
