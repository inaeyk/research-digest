# Research Digest

Research Digest is a local-first arXiv research digest for a single user. It stores
profiles, source settings, analyses, feedback, history, configuration, and backups
locally in SQLite and user config/data directories.

This first release is intentionally small: arXiv sources, title/abstract analysis,
lightweight history, daily scheduling support, diagnostics, and backup/export.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Confirm the installed command:

```bash
research-digest --version
research-digest status
```

## First run

Launch the UI through the supported release command:

```bash
research-digest serve
```

In the UI:

1. Create an interest profile on Interests.
2. Check the arXiv settings on Sources.
3. Check provider/data health on Settings.
4. Run a digest from Today.
5. Review previous runs in History.

Run a digest without the UI:

```bash
research-digest run
research-digest run --json
```

## Analyzer providers

The default analyzer is `codex`. It uses the Codex CLI and its saved
ChatGPT-managed authentication. It does not use `OPENAI_API_KEY`.

```bash
export RESEARCH_DIGEST_ANALYZER=codex
research-digest doctor
research-digest run
```

Make sure the `codex` executable is installed and already signed in with
ChatGPT before running live analysis.

To use the OpenAI API provider instead:

```bash
export RESEARCH_DIGEST_ANALYZER=openai
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5-mini
research-digest doctor
research-digest run
```

Never put API keys in the repository, SQLite database, or config file.

## Data and config locations

Research Digest stores persistent user data outside the source checkout by
default. Inspect the active paths with:

```bash
research-digest status
research-digest status --json
```

Useful non-secret overrides:

```bash
export RESEARCH_DIGEST_DB=/absolute/path/to/research_digest.sqlite3
export RESEARCH_DIGEST_DATA_DIR=/absolute/path/to/data-dir
export RESEARCH_DIGEST_CONFIG_DIR=/absolute/path/to/config-dir
```

Existing repo-local development databases can be adopted into the user data
directory during startup when no user-data DB exists. Explicit
`RESEARCH_DIGEST_DB` disables automatic adoption.

## Daily schedule

On WSL2, Research Digest can install a Windows Task Scheduler task that invokes
the installed headless command. Streamlit does not need to be running.

```bash
research-digest schedule install --time 07:30
research-digest schedule status
research-digest schedule remove
```

Schedule times are Windows local time and follow Windows daylight-saving rules.
The scheduled command includes non-secret runtime settings such as the active
SQLite path and, for Codex-backed schedules, the non-secret directory containing
the resolved `codex` executable. It does not embed API keys, Codex
authentication material, or copied auth files.

If Codex was installed through NVM or another user-local runtime manager, run
`research-digest schedule install ...` from an interactive shell where
`command -v codex` works. Reinstalling or updating the schedule refreshes the
recorded Codex runtime path after Node/Codex upgrades. `research-digest doctor`
warns when an installed Codex-backed schedule does not include the current
Codex executable directory.

## Doctor

Use doctor for bounded diagnostics:

```bash
research-digest doctor
research-digest doctor --json
research-digest doctor --network
```

Doctor checks Python/runtime support, data/config paths, SQLite/schema/config
versions, provider setup, scheduler status, last run health, and optional arXiv
network reachability. Output is sanitized and should not include secrets.

## Backup and export

Create a recoverable SQLite snapshot:

```bash
research-digest backup
```

Create a backup plus portable JSON export:

```bash
research-digest backup --export-json
research-digest backup --json --export-json
```

Backups use SQLite's backup API and validate the generated snapshot. Existing
destination files are not overwritten. JSON export contains user-owned semantic
data such as profiles, source settings, feedback, run summaries, and saved run
snapshots; it excludes provider secrets and authentication material.

To recover manually, stop running digest/UI processes, keep a copy of the
current active database, then replace the active SQLite file reported by
`research-digest status` with a validated backup.

## Upgrade expectations

Application code is replaceable. User data and configuration live outside the
source checkout by default and are upgraded through explicit SQLite schema and
JSON config version handling. Migration backups are created before
schema-changing DB upgrades where required.

Before upgrading an already-current installed/user-data database, run:

```bash
research-digest doctor
research-digest backup --export-json
```

For an older repo-local M2 development database, keep a separate copy of that
SQLite file first. On first startup without an existing user-data DB, Research
Digest adopts the copied legacy DB into the user data directory and creates its
own pre-migration backup before applying schema changes. After that migration,
use `research-digest backup --export-json` against the current active DB.

After upgrading, run:

```bash
research-digest status
research-digest doctor
```

## Known release limitations

- arXiv is the only source pool in this release.
- Analysis is abstract-level; full-paper/PDF deep reading is deferred.
- Lightweight History is not long-term semantic memory or trend analysis.
- The supported schedule backend is WSL2 through Windows Task Scheduler.
- This is a local single-user app; it does not provide authentication,
  multi-user access, cloud deployment, or a web service.

Post-release roadmap:

- M3: additional websites/source adapters.
- M5: full-paper/deep reading.
- M6: persistent research memory.

## Development checks

```bash
pytest
ruff check .
mypy --strict src tests
python -m compileall -q src tests
```

Tests use fixtures, mocks, and fake analyzers so deterministic checks do not
require live arXiv, Codex, or OpenAI access.
