# v0.2 Campaign Report

## Baseline Recovery

- CodeGraph: no `.codegraph/` directory exists at the repository root.
- Current branch at recovery: `master`, tracking local `origin/master`.
- Feature branch created: `feature/v0.2-date-native-scheduler-ui`.
- Current start commit: `70fdd312439342defdb1d4036cc71802c001af9c`.
- Released baseline: annotated tag `v0.1.0` targets
  `905f3133b58b6248fe4d3714c19f8bcdf9dde4cf`; tag object
  `be5925e7172ab788dde674669fd7d82068038b92`.
- Current package/runtime version: `0.1.0`.
- Current SQLite schema version: `4`.
- Current JSON config version: `1`.
- Current tracked worktree at recovery: clean.
- Online remote verification: `git ls-remote --heads --tags origin` failed with
  DNS resolution failure for `github.com`, including after network escalation.

## Baseline Evidence

- Complete local Git history and tags were inspected.
- `README.md`, `pyproject.toml`, AGENTS instructions, M2 campaign docs,
  release1 campaign docs, current source files, and current test files were
  inspected before implementation.
- Current baseline deterministic checks:
  - `pytest`: 149 passed.
  - `ruff check .`: PASS.
  - `mypy --strict src tests`: PASS.
  - `python -m compileall -q src tests`: PASS.

## Release1 Scheduler Behavior Recovered

- v0.1.0 scheduler support remains WSL2 through Windows Task Scheduler.
- The scheduled action invokes installed `research-digest run`.
- Codex-backed schedule install captures the non-secret directory containing the
  resolved `codex` executable in scheduled `PATH`.
- The scheduled action records non-secret runtime settings only.
- It must not embed `OPENAI_API_KEY`, `CODEX_API_KEY`, Codex auth files, access
  tokens, refresh tokens, or copied auth paths.
- `research-digest doctor` warns when an installed Codex-backed schedule lacks
  the current interactive Codex executable directory.

## Architecture Recovery Notes

- `research_digest.sources` provides the source adapter boundary.
- `ArxivSource.fetch()` currently uses `lookback_hours`, `max_results`,
  descending `submittedDate`, and local filtering by `Article.published_at`.
- `research_digest.pipeline.run_digest()` owns fetch, article upsert, cache
  lookup, M2 preselection, analyzer calls, run counters, and app run state.
- `research_digest.service` is the shared UI/CLI/scheduler boundary and owns run
  locking, calibration, synthesis, and snapshot persistence.
- `research_digest.history` currently persists immutable JSON run snapshots but
  does not yet include date-selection metadata.
- `research_digest.scheduler` owns WSL2/Windows Task Scheduler construction and
  status; Streamlit must call this service rather than duplicating command
  construction in U2-E.
- `research_digest.config` owns replaceable-code/data separation and versioned
  JSON config migration.
- `research_digest.db` owns ordered SQLite migrations and schema versioning.

## U2-A Status

Status: PASS after repair round 1 and fresh independent re-audit.

The frozen plan is recorded in `CAMPAIGN_STATE.md`.

Candidate work completed so far:

- Added normalized `DateSelection` domain support for latest available, single
  date, date range, and explicit dates.
- Raised JSON config to version 2 with a default latest-available date selection
  and v1/v0 migration backup behavior.
- Added date-native arXiv retrieval with `submittedDate` query bounds,
  pagination, duplicate arXiv id deduplication, UTC source-date coverage
  metadata, latest-available resolution, empty-date coverage, and internal
  safety-limit reporting.
- Documented arXiv source-date semantics in
  `ARXIV_SOURCE_DATE_SEMANTICS.md`.

Focused candidate verification so far:

- `pytest tests/test_models.py tests/test_arxiv.py tests/test_config.py`: 40 passed.
- focused `ruff check` over changed source/tests: PASS.
- `mypy --strict src tests`: PASS.

Initial independent U2-A Auditor:

- Auditor `01a00f89-de07-7a92-b5fe-36dd01c36845` returned FAIL with one
  IMPORTANT finding.
- Finding: sparse explicit date selections could scan intervening off-date API
  rows without counting them against the safety cap.
- Repair round 1 changes explicit non-contiguous date retrieval to per-date
  queries with global safety accounting and incomplete-date metadata when the
  cap is exhausted.
- Added regression coverage for sparse explicit dates, global safety cap
  exhaustion across explicit dates, and duplicate same-id/different-category
  rows.

Post-repair verification:

- `pytest`: 166 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live smoke:

- Bounded live arXiv latest-available smoke was attempted.
- Result: environment blocked by DNS resolution failure for `export.arxiv.org`
  before and after network escalation.

Fresh U2-A re-audit:

- Auditor `01a00f8e-1ae5-7f62-9d70-06fe7708d80c` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- The auditor confirmed the sparse explicit-date repair, date-selection
  normalization, UTC source-date documentation, pagination, latest available,
  empty-date coverage, safety-cap behavior, stable-id/category duplicate
  handling, backward config migration, and legacy `ArxivSource.fetch()`
  compatibility.
- Deferred OPTIONAL: consider a future raw API-row/page scan ceiling for
  malformed or inconsistent API responses.

U2-A freeze:

- qualified commit: `616d84209c7295de2884d4ae82df0a5bd222d397`.
- qualified tag: `u2a-qualified`.
- qualified tag object: `84e22c2eaa2b67c1dc6000fe4cc42e25a7f32e7c`.
