# v0.2 Release Candidate Human Review Packet

Status: release-candidate preparation in progress; final human release decision
required.

This packet is release-candidate material only. It does not authorize a public
release, public `v0.2.0` tag, GitHub release, package publication, or remote
push.

## Versioning

- package version in `pyproject.toml`: `0.2.0`
- runtime version in `src/research_digest/__init__.py`: `0.2.0`
- released baseline: annotated tag `v0.1.0` targets
  `905f3133b58b6248fe4d3714c19f8bcdf9dde4cf`
- current qualification branch: `feature/v0.2-date-native-scheduler-ui`
- release-candidate commit: `56472ce94ee65c70c7700ceb5dbd9fe20d4f1038`
- suggested final public release tag for human review: `v0.2.0`

## Release Notes

Research Digest `0.2.0` moves the ordinary workflow from development-oriented
retrieval knobs to source-date digests.

Major features:

- date-native manual digests for latest available, single date, date range, and
  selected non-contiguous dates
- retrieval of all eligible arXiv articles for selected source dates, with M2
  preselection/cache controlling new-analysis effort
- arXiv source-date semantics documented as the UTC calendar date of the
  official Atom `published` timestamp
- date-native headless automatic catch-up for missed source dates
- scheduler management in Settings, including enable/disable, daily time,
  catch-up toggle, status, next run, last scheduled run, last outcome, Run Now,
  and unsupported-environment messaging
- date-oriented History that shows requested/covered source dates, manual vs
  scheduled origin, counts, run time, and persisted synthesis
- Settings polish for General, Analysis, Automation, Data, and Health
- Backup now and optional JSON export from Settings

## Upgrade Notes From v0.1.0

Before upgrading an existing installation:

```bash
research-digest doctor
research-digest backup --export-json
```

Expected upgrade behavior:

- application code remains replaceable and user data/config survives outside
  the source checkout
- SQLite schema upgrades from v0.1.0 schema 4 to schema 6 with migration
  backups
- JSON config upgrades from v0.1.0 config 1 to config 3 with a config backup
- legacy historical runs remain historical rolling-lookback runs and are not
  reinterpreted as exact source-date coverage
- stored arXiv `lookback_hours` and `max_results` values are preserved for
  compatibility, but normal UI runs no longer use them as primary controls
- first automatic coverage anchor is conservative so upgrade does not
  surprise-backfill the full arXiv archive
- existing compatible scheduler configuration can be inspected and updated
  through Settings without duplicating the task

After upgrade:

```bash
research-digest status
research-digest doctor
```

## Date Selection Guide

Use Today to choose the source dates:

- Latest available: resolves through the arXiv source adapter to a date with
  eligible material.
- Single date: digests one explicit UTC arXiv source date.
- Date range: digests every source date in a contiguous range.
- Selected dates: digests explicit non-contiguous dates.

The UI shows the exact date or date set before the run starts and again in the
result. Internal retrieval safety limits are not user effort controls; if a
safety limit is reached, the run is reported as incomplete/partial.

## Scheduler UI Guide

Use Settings -> Automation for normal scheduling:

- turn automatic daily digest on or off
- set daily time in Windows local time
- see daylight-saving semantics
- enable or disable catch-up for missed source dates
- inspect installed state, health/warnings, next run, last scheduled run, and
  last scheduled digest outcome
- Run now using the same automatic catch-up service used by scheduled runs
- Disable schedule

Administrative CLI commands remain available for power users:

```bash
research-digest schedule install --time 07:30
research-digest schedule status
research-digest schedule remove
```

The WSL2/Windows Task Scheduler action preserves the v0.1.0 Codex PATH safety:
it records the non-secret directory containing the resolved `codex` executable
and does not embed API keys, Codex auth material, copied auth paths, access
tokens, or refresh tokens.

## Schema And Config Changes

- SQLite schema 5 adds immutable app-run date metadata:
  run origin, date selection, requested/covered/empty/incomplete source dates,
  retrieval completeness, and safety-limit metadata.
- SQLite schema 6 adds source-date coverage scoped by profile semantic
  fingerprint and source semantic fingerprint.
- JSON config 2 adds a default date selection.
- JSON config 3 adds automatic catch-up settings and a conservative automatic
  coverage start date.

## Backup And Recovery

Use Settings -> Data -> Backup now, optionally with JSON export, or use:

```bash
research-digest backup
research-digest backup --export-json
```

Backups use SQLite's backup API and validate the generated snapshot. Existing
destinations are not overwritten. JSON export contains user-owned semantic data
and excludes provider secrets/authentication material.

Manual recovery:

1. Stop running digest/UI processes.
2. Keep a copy of the current active database path from Settings or
   `research-digest status`.
3. Replace the active SQLite file with a validated backup.
4. Run `research-digest doctor`.

## Known Limitations

- arXiv-only source family
- abstract-level analysis only
- no PDF/full-paper reading
- no Library/tagging/notes/collections
- no long-term semantic research memory
- local single-user application; no authentication, multi-user access, cloud
  deployment, or public web service
- first-class scheduler environment remains WSL2 plus Windows Task Scheduler

## Deferred Optional Findings

- Future hardening could add a separate raw API-row/page scan ceiling for
  malformed or inconsistent arXiv API responses.
- History could surface Partial directly in the selectbox/status label and
  format requested/covered detail captions as friendly dates.
- Settings backup-directory display could import `backup.DEFAULT_BACKUP_DIRNAME`
  instead of spelling the current directory name inline.

## Human Release Commands

Do not run these automatically. After human acceptance, expected commands are
approximately:

```bash
git status
git log --oneline --decorate -n 5
git tag -a v0.2.0 <RC_COMMIT> -m "Research Digest 0.2.0"
git push origin feature/v0.2-date-native-scheduler-ui
git push origin u2a-qualified u2b-qualified u2c-qualified u2d-qualified u2e-qualified u2f-qualified u2g-qualified u2h-qualified v0.2.0
```

The human may choose different merge, remote, and tag policy.
