# 🗂 repo-reporter

**Instant onboarding reports for any code repository.**

Drop `repo-reporter` on a repo and get a structured Markdown (+ HTML) report telling a new developer exactly where to start, what's risky, and where the gaps are — in under a minute.

---

## What it produces

```
# Repo Health & Onboarding Report — my-project

## 📊 Repository Overview
Total files · Languages · Lines of code

## 🚀 Start Here
Top 3-5 files a new dev should read first

## ⚠️ Risk Flags
Files with no docs · no tests · high TODOs · oversized functions

## 📁 Module Summaries
2-3 sentence plain-English description of every significant file
```

---

## Install

**Requirements:** Python 3.8+

```bash
# Clone and install in one step
git clone https://github.com/you/repo-reporter
cd repo-reporter
pip install -e .
```

Or install just the dependencies without the package entry point:

```bash
pip install -r requirements.txt
python -m repo_reporter.cli scan <path-to-repo>
```

---

## Usage

```bash
# Print Markdown report to stdout
repo-reporter scan /path/to/your/repo

# Save Markdown report to a file
repo-reporter scan /path/to/your/repo --output report.md

# Save both Markdown + HTML into the repo root
repo-reporter scan /path/to/your/repo --format both

# Save both into a specific directory
repo-reporter scan /path/to/your/repo --format both --output ./reports

# HTML only (great for sharing with non-technical stakeholders)
repo-reporter scan /path/to/your/repo --format html --output report.html
```

### All options

```
Usage: repo-reporter scan [OPTIONS] <path-to-repo>

Options:
  -f, --format [markdown|html|both]  Output format.  [default: markdown]
  -o, --output PATH                  Where to save the report.
                                     markdown/html → file path (default: stdout)
                                     both          → directory  (default: repo root)
  --help                             Show this message and exit.
```

---

## Example run

```bash
$ repo-reporter scan ~/projects/django --format both --output ./reports
Scanning…
Analysing 312 files…
  Written: reports/report.md
  Written: reports/report.html
```

Open `reports/report.html` in a browser — it's self-contained, no server needed.

---

## Project structure

```
repo_reporter/
├── cli.py          Entry point — Click commands, error handling
├── scanner.py      Walks the repo, collects per-file signals
├── analyser.py     Builds plain-English summaries and risk flags
└── reporter.py     Renders Markdown and HTML output
```

**Data flow:**

```
Path on disk
  └─▶ RepoScanner.scan()        →  ScanResult (list of FileInfo)
        └─▶ RepoAnalyser.analyse()  →  list of ModuleFinding
              └─▶ ReportGenerator.write()  →  report.md + report.html
```

---

## What gets flagged

| Flag | Meaning |
|------|---------|
| 📄 `NO_DOCS` | No comments or docstrings found |
| 🧪 `NO_TESTS` | No corresponding test file detected |
| 📝 `HIGH_TODO` | 5 or more TODO/FIXME/HACK markers |
| 📏 `LONG_FILE` | File exceeds 300 lines |
| 🔬 `LONG_FUNCTIONS` | A function or class body exceeds 50 lines |

Directories skipped automatically: `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, `build`, and more.

---

## Extending repo-reporter

The pipeline is intentionally simple — three stages, each a plain Python class.
Common extension points:

| What you want | Where to change |
|---------------|-----------------|
| Support a new language | `EXT_TO_LANG` + `LANG_COMMENT_PATTERNS` in `scanner.py` |
| Add a new risk flag | `_build_risks()` in `analyser.py` |
| Add a report section | `MarkdownReporter` in `reporter.py` |
| Change "Start Here" ranking | `_start_here_score()` in `reporter.py` |

---

## Possible quick enhancement — CI / pre-commit integration

Add a `--fail-on-risks` flag that exits with code 1 when any file has risk flags.
Drop it in a GitHub Actions step or pre-commit hook:

```yaml
# .github/workflows/onboarding-report.yml
- name: Check repo health
  run: repo-reporter scan . --fail-on-risks
```

Implementation is ~10 lines in `cli.py`:

```python
@click.option("--fail-on-risks", is_flag=True,
              help="Exit with code 1 if any risk flags are found.")
def scan(..., fail_on_risks):
    ...
    if fail_on_risks and any(f.risks for f in findings):
        risky = sum(1 for f in findings if f.risks)
        _die(f"{risky} file(s) have risk flags. Fix them or update thresholds.")
```

---

*Summaries are derived from static analysis — no LLM, no network calls, no API keys.*
