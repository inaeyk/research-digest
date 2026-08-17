# Release Candidate Human Review Packet

Status: draft for final release-candidate gate.

This packet is release-candidate material only. It does not authorize a public release, public version tag, GitHub release, package publication, or remote push.

## Versioning

- package version in `pyproject.toml`: `0.1.0`
- runtime version in `src/research_digest/__init__.py`: `0.1.0`
- existing public-style version tags: none found by `git tag --list 'v*'`
- suggested final public release tag for human review: `v0.1.0`

The release campaign has local qualification tags through `m7i-qualified`; the final public version tag has not been created.

## Release Notes

Research Digest `0.1.0` is a local-first single-user arXiv research digest.

Included:

- interest profiles and arXiv source settings
- abstract-level relevance analysis through Codex CLI by default or optional OpenAI API provider
- preselection, feedback calibration context, and cross-paper synthesis
- lightweight run history and saved run snapshots
- headless CLI operation: `run`, `status`, `doctor`, `backup`, `serve`, and `schedule`
- WSL2/Windows Task Scheduler command construction for daily headless runs
- versioned SQLite schema migrations with pre-migration backups
- versioned JSON configuration outside the source checkout
- release UI with Today, History, Interests, Sources, and Settings
- SQLite backup plus optional deterministic JSON semantic export
- offline wheel/editable packaging path with installed `research-digest` console script

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
research-digest --version
research-digest status
```

In an environment with package-index access, dependencies are declared as:

- `openai>=1.99.0`
- `streamlit>=1.51.0`

The release qualification environment could build and install the package without downloading dependencies, but full dependency download from PyPI remained DNS-blocked.

## First Run

```bash
research-digest serve
```

Then configure:

1. Interests: create an interest profile.
2. Sources: review arXiv categories, lookback, and max results.
3. Settings: check provider, data/config paths, version, and doctor summary.
4. Today: run a digest.
5. History: inspect previous runs.

Headless run:

```bash
research-digest run
research-digest run --json
```

## Upgrade From Development/M2 Installations

Before upgrade:

```bash
research-digest doctor
research-digest backup --export-json
```

Upgrade expectations:

- user data/config live outside the source checkout by default
- schema/config versions are explicit
- existing M2-style data is adopted from a copy and migrated with a pre-migration backup
- repeated startup does not duplicate semantic data or migrations
- code is replaceable while user data survives independently

After upgrade:

```bash
research-digest status
research-digest doctor
```

## Scheduler

```bash
research-digest schedule install --time 07:30
research-digest schedule status
research-digest schedule remove
```

The WSL2/Windows scheduled action invokes the installed headless CLI, not Streamlit. It includes non-secret runtime settings and excludes API keys/Codex authentication material.

Live Task Scheduler probing in this environment is blocked by WSL socket errors; deterministic scheduler command construction, idempotency, status, and secret-exclusion behavior are covered by tests.

## Backup And Recovery

```bash
research-digest backup
research-digest backup --export-json
research-digest backup --json --export-json
```

Backups use SQLite's backup API and validate the generated snapshot. Existing destinations are not overwritten. JSON export includes user-owned semantic data and excludes provider secrets/authentication material.

Manual recovery:

1. Stop running digest/UI processes.
2. Keep a copy of the current active database path from `research-digest status`.
3. Replace the active SQLite file with a validated backup.
4. Run `research-digest doctor`.

## Codex Authentication

Default provider:

```bash
export RESEARCH_DIGEST_ANALYZER=codex
codex --version
research-digest doctor
research-digest run
```

The Codex provider uses the installed Codex CLI and its saved ChatGPT-managed authentication. Do not store Codex tokens in the repository, SQLite database, config file, scheduler command, or release docs.

Live Codex model execution was attempted in this environment and blocked by local filesystem/network transport limits. This must be rechecked by the human in a normal authenticated environment before public release acceptance.

## Optional OpenAI API Provider

```bash
export RESEARCH_DIGEST_ANALYZER=openai
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5-mini
research-digest doctor
research-digest run
```

Do not persist API keys in the repository, SQLite database, or JSON config.

## Known Limitations

- arXiv-only source pool
- abstract-level analysis rather than full-paper/PDF reading
- no M6-style long-term semantic research memory or trend analysis
- local single-user application with no authentication, multi-user access, cloud deployment, or public web service
- supported schedule backend is WSL2 through Windows Task Scheduler
- live arXiv/Codex/scheduler/serve smoke tests were environment-blocked in this campaign session where noted

## Deferred Findings

- No BLOCKER, IMPORTANT, MINOR, or OPTIONAL findings remained after M7-I second closure audit.
- Final release audit may add new findings that must be resolved or carried into this packet before human decision.

## Post-Release Roadmap

- M3: additional websites/source adapters
- M5: full-paper/deep reading
- M6: persistent research memory

## Proposed Human Release Commands

After final release-candidate PASS and human acceptance, proposed commands are:

```bash
git status
git log --oneline --decorate -n 5
git tag -a v0.1.0 -m "Research Digest 0.1.0"
git push origin master
git push origin m7g-qualified m7h-qualified m7i-qualified v0.1.0
```

The human may choose different remote/tag policy. The campaign must not run these commands automatically.
