"""CLI entrypoint for repo-reporter."""

import sys
from pathlib import Path

import click

from repo_reporter.scanner import RepoScanner
from repo_reporter.analyser import RepoAnalyser
from repo_reporter.reporter import ReportGenerator


@click.group()
@click.version_option(package_name="repo-reporter")
def cli():
    """Repo Health & Onboarding Reporter.

    Scans a code repository and produces a plain-English onboarding
    report for a new developer joining the project.
    """


@cli.command()
@click.argument("repo_path", metavar="<path-to-repo>",
                type=click.Path(file_okay=False, resolve_path=True))
@click.option("--output", "-o", default=None, metavar="PATH",
              help=(
                  "Where to save the report. "
                  "For --format markdown/html: a file path (default: stdout). "
                  "For --format both: a directory (default: repo root)."
              ))
@click.option("--format", "-f", "fmt",
              type=click.Choice(["markdown", "html", "both"], case_sensitive=False),
              default="markdown",
              show_default=True,
              help="Output format.")
def scan(repo_path: str, output: str | None, fmt: str):
    """Scan a repository and produce an onboarding report.

    \b
    Examples:
      repo-reporter scan /path/to/repo
      repo-reporter scan /path/to/repo --format both
      repo-reporter scan /path/to/repo --format both --output ./reports
      repo-reporter scan /path/to/repo --output report.md
      repo-reporter scan /path/to/repo --format html --output report.html
    """
    repo = _validate_repo(repo_path)

    # --- scan ---
    click.echo("Scanning…", err=True)
    try:
        result = RepoScanner(repo).scan()
    except PermissionError as exc:
        _die(f"Permission denied while reading the repository:\n  {exc}")

    _check_not_empty(result, repo)

    # --- analyse ---
    click.echo(f"Analysing {len(result.files)} files…", err=True)
    findings = RepoAnalyser(result).analyse()
    gen      = ReportGenerator(result, findings)

    # --- output ---
    if fmt == "both":
        out_dir = Path(output) if output else repo
        _ensure_dir(out_dir)
        try:
            written = gen.write(out_dir, html=True)
        except PermissionError as exc:
            _die(f"Cannot write to output directory:\n  {exc}")
        for p in written:
            click.echo(f"  Written: {p}", err=True)
        return

    content = gen.generate_html() if fmt == "html" else gen.generate()

    if output:
        out_path = Path(output)
        _ensure_dir(out_path.parent)
        try:
            out_path.write_text(content, encoding="utf-8")
        except PermissionError as exc:
            _die(f"Cannot write to {out_path}:\n  {exc}")
        click.echo(f"  Written: {out_path}", err=True)
    else:
        click.echo(content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_repo(repo_path: str) -> Path:
    """Return a resolved Path, or exit with a clear message."""
    if not repo_path:
        _die("No path provided. Usage: repo-reporter scan <path-to-repo>")

    repo = Path(repo_path)

    if not repo.exists():
        _die(
            f"Path does not exist: {repo}\n"
            "  Check the path and try again."
        )
    if not repo.is_dir():
        _die(
            f"Path is a file, not a directory: {repo}\n"
            "  Provide the root directory of a repository."
        )
    if not any(True for _ in repo.iterdir()):
        _die(
            f"Directory is empty: {repo}\n"
            "  Point repo-reporter at a repository with source files."
        )
    return repo


def _check_not_empty(result, repo: Path) -> None:
    """Warn (but don't abort) if no recognisable source files were found."""
    if not result.files:
        click.echo(
            f"Warning: no source files found under {repo}.\n"
            "  All files may have been skipped (node_modules, venv, .git, etc.).\n"
            "  The report will be mostly empty.",
            err=True,
        )


def _ensure_dir(path: Path) -> None:
    """Create directory (and parents) if it doesn't exist."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        _die(f"Cannot create directory {path}:\n  {exc}")


def _die(message: str) -> None:
    """Print an error and exit with code 1."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(1)
