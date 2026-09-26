"""architect.py — Codebase Architecture Extraction.

Walks the repository, maps the folder structure, extracts inter-file import
dependencies, and generates a Mermaid.js diagram that can be embedded in any
Markdown document or rendered directly at mermaid.live.

Two diagrams are produced:
  1. Folder / module tree  — flowchart TD showing directories and files
  2. Dependency graph      — flowchart LR showing which module imports which

Usage
-----
    from repo_reporter.architect import build_architecture_diagram

    md = build_architecture_diagram("/path/to/repo")
    print(md)   # contains two ```mermaid fenced blocks
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple


# ---------------------------------------------------------------------------
# Directories to skip (mirrors scanner.py convention)
# ---------------------------------------------------------------------------
SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn",
    "node_modules",
    "venv", ".venv", "env", ".env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", "dist", "build",
    ".idea", ".vscode",
    "vendor", "site-packages",
}

# Source extensions we care about for dependency tracing
SOURCE_EXTS: set[str] = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".go", ".rb", ".rs",
}

# Max nodes before we truncate to keep diagrams readable
MAX_TREE_NODES  = 60
MAX_EDGE_NODES  = 40


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ArchResult:
    """Result returned by extract_architecture()."""
    repo_name:   str
    tree_nodes:  List[str]          # (id, label, parent_id | None)
    dep_edges:   List[Tuple[str, str]]  # (from_module, to_module)
    all_modules: List[str]          # all discovered module paths (relative)
    truncated:   bool = False       # True when diagram was clipped for size


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_architecture_diagram(repo_path: str | Path) -> str:
    """
    Analyse the repo and return a Markdown string containing:
      - A prose introduction
      - A Mermaid folder-tree diagram
      - A Mermaid dependency-graph diagram

    Parameters
    ----------
    repo_path : path to the root of the repository to analyse
    """
    repo = Path(repo_path).resolve()
    result = extract_architecture(repo)
    return _render_markdown(result)


def extract_architecture(repo: Path) -> ArchResult:
    """Walk the repo and return an ArchResult (no rendering)."""
    repo_name = repo.name
    all_modules: list[str] = []
    dep_edges: list[tuple[str, str]] = []

    # Collect all source files
    source_files: list[Path] = []
    for f in repo.rglob("*"):
        if f.is_file() and not _is_skipped(f) and f.suffix in SOURCE_EXTS:
            source_files.append(f)
            all_modules.append(str(f.relative_to(repo)))

    # Build dependency edges
    for f in source_files:
        imports = _extract_imports(f, repo)
        for imp in imports:
            dep_edges.append((str(f.relative_to(repo)), imp))

    # Deduplicate edges and remove self-loops
    dep_edges = list(dict.fromkeys(
        (a, b) for a, b in dep_edges if a != b
    ))

    # Build tree nodes from directory structure
    tree_nodes = _build_tree_nodes(repo, source_files)

    truncated = (
        len(tree_nodes) > MAX_TREE_NODES
        or len(dep_edges) > MAX_EDGE_NODES
    )

    return ArchResult(
        repo_name=repo_name,
        tree_nodes=tree_nodes[:MAX_TREE_NODES],
        dep_edges=dep_edges[:MAX_EDGE_NODES],
        all_modules=all_modules,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Tree builder
# ---------------------------------------------------------------------------

def _build_tree_nodes(repo: Path, source_files: list[Path]) -> list[str]:
    """
    Return a list of Mermaid node-definition strings for the folder tree.
    Format:  (node_id, label, parent_id)   — used later in rendering.
    """
    seen_dirs: set[Path] = set()
    entries: list[tuple[str, str, str | None]] = []

    def _dir_id(p: Path) -> str:
        rel = p.relative_to(repo)
        return "d_" + re.sub(r"[^\w]", "_", str(rel)) if str(rel) != "." else "root"

    def _file_id(p: Path) -> str:
        rel = p.relative_to(repo)
        return "f_" + re.sub(r"[^\w]", "_", str(rel))

    # Root
    entries.append(("root", repo.name + "/", None))

    for f in sorted(source_files):
        # Ensure all ancestor dirs are in the tree
        for parent in reversed(f.relative_to(repo).parents):
            abs_parent = repo / parent
            if abs_parent == repo or abs_parent in seen_dirs:
                continue
            seen_dirs.add(abs_parent)
            grandparent = abs_parent.parent
            gp_id = _dir_id(grandparent) if grandparent != repo.parent else "root"
            entries.append((_dir_id(abs_parent), parent.name + "/", gp_id))

        # File node — parent is its immediate directory
        parent_dir = f.parent
        parent_id  = _dir_id(parent_dir) if parent_dir != repo else "root"
        entries.append((_file_id(f), f.name, parent_id))

    return entries  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Import extractor
# ---------------------------------------------------------------------------

_PY_IMPORT_RE  = re.compile(
    r"^(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.MULTILINE
)
_JS_IMPORT_RE  = re.compile(
    r"""(?:import|require)\s*[\({'"]([\.\/][\w\.\/\-]+)""", re.MULTILINE
)
_GO_IMPORT_RE  = re.compile(r'"(\.\/[\w\.\/]+)"', re.MULTILINE)


def _extract_imports(file_path: Path, repo: Path) -> list[str]:
    """
    Return a list of *relative* module paths that file_path imports from
    within the same repo.  Only intra-repo dependencies are returned.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    ext  = file_path.suffix
    base = file_path.parent

    deps: list[str] = []

    if ext == ".py":
        for m in _PY_IMPORT_RE.finditer(source):
            raw = (m.group(1) or m.group(2) or "").strip()
            if not raw:
                continue
            # Convert dotted module path to a relative file path
            candidate = repo / Path(raw.replace(".", "/"))
            for suffix in (".py", "/__init__.py"):
                p = Path(str(candidate) + suffix) if not suffix.startswith("/") \
                    else Path(str(candidate) + "/").with_suffix("") / "__init__.py"
                # Try direct: repo/repo_reporter/scanner.py
                direct = repo / (raw.replace(".", "/") + ".py")
                if direct.exists():
                    deps.append(str(direct.relative_to(repo)))
                    break

    elif ext in (".js", ".jsx", ".ts", ".tsx"):
        for m in _JS_IMPORT_RE.finditer(source):
            raw = m.group(1)
            resolved = (base / raw).resolve()
            for suffix in ("", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"):
                p = Path(str(resolved) + suffix)
                if p.exists() and repo in p.parents:
                    deps.append(str(p.relative_to(repo)))
                    break

    elif ext == ".go":
        for m in _GO_IMPORT_RE.finditer(source):
            raw = m.group(1)
            resolved = (base / raw).resolve()
            if resolved.exists() and repo in resolved.parents:
                deps.append(str(resolved.relative_to(repo)))

    return deps


# ---------------------------------------------------------------------------
# Skip helper
# ---------------------------------------------------------------------------

def _is_skipped(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


# ---------------------------------------------------------------------------
# Mermaid renderer
# ---------------------------------------------------------------------------

def _safe_id(s: str) -> str:
    """Make a string safe to use as a Mermaid node id."""
    return re.sub(r"[^\w]", "_", s)


def _render_markdown(r: ArchResult) -> str:
    """Render an ArchResult into a Markdown string with two Mermaid diagrams."""
    sections: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    sections.append(f"## 🏗 Architecture — `{r.repo_name}`\n")
    sections.append(
        f"_{len(r.all_modules)} source file(s) discovered. "
        + ("Diagrams clipped for readability. " if r.truncated else "")
        + "Render at [mermaid.live](https://mermaid.live)._\n"
    )

    # ── Diagram 1: Folder / module tree ─────────────────────────────────────
    sections.append("### 📁 Module Tree\n")
    tree_lines = ["```mermaid", "flowchart TD"]

    node_set = {entry[0] for entry in r.tree_nodes}

    for nid, label, parent_id in r.tree_nodes:
        safe = _safe_id(nid)
        # directories → rounded rect; files → plain rect
        if label.endswith("/"):
            tree_lines.append(f'    {safe}("{label}")')
        else:
            tree_lines.append(f'    {safe}["{label}"]')

        if parent_id and parent_id in node_set:
            tree_lines.append(f"    {_safe_id(parent_id)} --> {safe}")

    tree_lines.append("```")
    sections.append("\n".join(tree_lines))

    # ── Diagram 2: Dependency graph ──────────────────────────────────────────
    if r.dep_edges:
        sections.append("\n### 🔗 Import Dependency Graph\n")
        dep_lines = ["```mermaid", "flowchart LR"]

        # Collect unique nodes from edges
        edge_nodes: set[str] = set()
        for a, b in r.dep_edges:
            edge_nodes.add(a)
            edge_nodes.add(b)

        for n in sorted(edge_nodes):
            safe = _safe_id(n)
            dep_lines.append(f'    {safe}["{Path(n).name}"]')

        for a, b in r.dep_edges:
            dep_lines.append(f"    {_safe_id(a)} --> {_safe_id(b)}")

        dep_lines.append("```")
        sections.append("\n".join(dep_lines))
    else:
        sections.append(
            "\n_No intra-repo import dependencies detected "
            "(or repo uses a language without import tracing support)._"
        )

    return "\n".join(sections) + "\n"
