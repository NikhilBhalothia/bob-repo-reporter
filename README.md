# repo-reporter 📋

**Instant onboarding reports for any codebase — built with IBM Bob 2.0**

`repo-reporter` scans a code repository and generates a plain-English report that answers the question every new developer asks on day one: *"Where do I even start?"*

Built for the **IBM Bob 2.0 Hackathon** (lablab.ai).

---

## The problem

Joining an unfamiliar codebase is slow. There's no map — you don't know which files matter, which ones are undocumented landmines, or where the tests (if any) live. Senior developers spend hours walking new hires through a repo that a tool could summarize in seconds.

## What it does

Point `repo-reporter` at any folder and it generates a report covering:

- **Repo overview** — file count, languages used, total lines of code
- **"Start here"** — the handful of files most important to read first
- **Risk flags** — files with no docs, no tests, high TODO/FIXME density, or oversized functions
- **Per-module summaries** — a 2–3 sentence, plain-English explanation of what each major file/module actually does

Output is generated as both **Markdown** (`report.md`) and **HTML** (`report.html`).

## Installation

```bash
git clone https://github.com/NikhilBhalothia/bob-repo-reporter.git
cd bob-repo-reporter
pip install -e .
```

## Usage

```bash
repo-reporter scan <path-to-repo> --format both
```

Example — scanning the tool's own repo:

```bash
repo-reporter scan . --format both
```

This produces `report.md` and `report.html` in the current directory. Open either in your editor or browser to see the full onboarding report.

### Flags

| Flag | Description |
|---|---|
| `--format` | `md`, `html`, or `both` (default: `md`) |
| `--output` | Custom output path/directory for the generated report(s) |

## How it works

1. **Scan** — walks the repo, collecting per-file stats (language, line count, docstring presence, TODO/FIXME count, test-file heuristics). Skips `.git`, `node_modules`, `venv`, `__pycache__`, and similar noise.
2. **Analyze** — for each significant module, generates a plain-English summary of its purpose and flags anything risky (missing docs/tests, high TODO density).
3. **Report** — compiles everything into a single readable Markdown/HTML report, structured so a new developer can get oriented in under 5 minutes.

## Project structure

```
repo_reporter/
├── __init__.py          # package + __version__
├── __main__.py          # python -m repo_reporter support
├── cli.py               # CLI entrypoint (scan subcommand)
├── scanner/
│   └── scanner.py       # scan_repo() → findings dict
└── reporter/
    └── reporter.py       # build_report(findings) → str
pyproject.toml            # package metadata + console_script entry point
bob_sessions/              # Screenshots of the Bob build sessions (see below)
```

## Built with IBM Bob 2.0

This project was built end-to-end in collaborative sessions with Bob 2.0, IBM's AI development partner — scaffolding, scanner logic, the AI-powered summarization layer, report generation, and final polish. Session summaries and screenshots documenting each build stage are in [`bob_sessions/`](./bob_sessions).

## Team

Built by a team of 4 for the IBM Bob 2.0 Hackathon.

## Demo

📹 [Demo video link here]

## License

MIT
