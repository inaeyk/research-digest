# Release 1 Campaign Report

## Baseline Recovery

- local HEAD: `8861682832aea1c5cd7dd3d580adecd98cd809a5` (`Record M2 final end gate`).
- local branch state: `master` tracks `origin/master`; both local refs currently point at `8861682832aea1c5cd7dd3d580adecd98cd809a5`.
- worktree hygiene: clean tracked tree; ignored local state includes `research_digest.sqlite3`, `.env`, `.venv`, Python/tool caches, and local agent/runtime directories.
- CodeGraph: no `.codegraph/` directory exists, so repository inspection used Git and direct file reads.
- online remote verification: attempted `git ls-remote --heads --tags origin`; failed with DNS resolution error for `github.com` both inside the default sandbox and after network escalation. This is recorded as an environment verification gap, not as evidence of remote mismatch.

## Qualified Baseline Tags

- `m1-qualified`: commit `36bd1cbe60f95d588e8ccdd41bfce914e9b1d7da`; tag object `be28fdfc5512e8d38a79956161407fef9a87eca4`.
- `m2a-qualified`: commit `81d4d5e011c46650c6094db628668e82a030547e`; tag object `e4f09071a4c7f04f5ad9d3238942b2ffbf42a5f0`.
- `m2b-qualified`: commit `9aea33b0a1dc8a2b34ad7622e55bb8fb047852bb`; tag object `0a81deaf52d6d4ffa49659b59a7decbd87fd2905`.
- `m2c-qualified`: commit `f6cbe703ae41657120105237fab221f56c2dc9e4`; tag object `bdcba8f788ad09f6e40d233b6a50d9a7a94335fb`.
- `m2d-qualified`: commit `1626793ef693fec068a1fa571a40d07c9ffb5233`; tag object `9af78da08af41a82b46b3318f77d600dfb0c5ff6`.
- `m2-qualified`: commit `8861682832aea1c5cd7dd3d580adecd98cd809a5`; tag object `44ad1f4bd1c7bbaf09d9b430e6b16693ff8d9536`.

## Campaign Scope

The release1 campaign deliberately skips M3, M5, and M6. Those remain post-release optional feature campaigns:

- M3: additional source adapters.
- M5: full-paper/deep reading.
- M6: persistent long-term research memory.

Active scope:

- M4: automatic daily operation.
- M7: release engineering, upgradeability, and productization.
- First release candidate only.

Architectural invariant:

- Future M3/M5/M6 capabilities must be additive upgrades, not rewrites of the current source adapter, analyzer, pipeline, CLI, data, or configuration architecture.

## M4-A Specification Freeze

M4-A is frozen as headless application execution through a stable core service boundary and CLI command conceptually equivalent to `research-digest run`.

The detailed frozen specification is maintained in `docs/campaigns/release1/CAMPAIGN_STATE.md`.

Status: implemented as a candidate and sent to fresh independent read-only audit.

## M4-A Candidate

Implementation summary:

- Added `research_digest.service` as the shared application boundary for one-profile and all-enabled-profile digest execution.
- Added `research_digest.analysis.providers` so analyzer construction no longer depends on Streamlit helpers.
- Added `research_digest.cli` with `research-digest run` and `research-digest run --json`.
- Registered the installed command entry point in `pyproject.toml`.
- Updated the Today page to call `run_digest_for_profile` rather than invoking pipeline orchestration directly.

Deterministic verification:

- `pytest`: 73 passed.
- `ruff check .`: PASS.
- strict `mypy src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Focused coverage added:

- headless execution processes all enabled profiles and skips disabled profiles.
- per-profile failures are sanitized and do not prevent subsequent enabled profiles from running.
- no enabled profiles returns deterministic command failure.
- JSON CLI output contains aggregate counts and omits profile descriptions, article titles, and abstracts.
- analyzer-unavailable CLI output is sanitized.
- Codex provider construction works without `OPENAI_API_KEY`.

Live verification:

- Isolated Research Digest service smoke with temporary SQLite DB and static one-article source reached the new headless service boundary but returned a sanitized Codex provider failure.
- Direct `codex exec` probe with the default Codex home fails before model work with `failed to initialize in-process app-server client: Read-only file system`.
- Direct `codex exec` probe with throwaway writable `CODEX_HOME` gets past initialization but cannot connect to `api.openai.com` from this session (`Operation not permitted` / stream disconnected), including after sandbox escalation.
- No API keys, Codex auth material, article contents, or personal SQLite data were written to campaign documents.

Initial audit:

- Fresh independent M4-A Auditor returned FAIL with one IMPORTANT finding: analyzer-unavailable CLI runs exited `0`.

Repair round 1:

- Changed `research-digest run` to return exit `1` and report status `failed` when the configured analyzer is unavailable.
- Preserved existing M2 behavior where the service/pipeline can fetch/store and persist an `analysis_unavailable` app run when analysis cannot execute.
- Updated CLI tests to require nonzero analyzer-unavailable exit semantics.

Repair verification:

- focused `pytest tests/test_cli.py tests/test_service.py tests/test_analyzer_providers.py`: 9 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.

Re-audit:

- Fresh independent M4-A re-auditor returned PASS with no BLOCKER/IMPORTANT findings.
- Re-auditor independently verified the analyzer-unavailable exit repair, no Streamlit import dependency for CLI/service/provider imports, shared UI/CLI service boundary, enabled-profile handling, M2 cache/reuse delegation, JSON privacy coverage, and Codex provider construction without `OPENAI_API_KEY`.

Re-auditor verification:

- `pytest -q -p no:cacheprovider tests/test_cli.py tests/test_service.py tests/test_analyzer_providers.py`: 9 passed.
- `pytest -q -p no:cacheprovider`: 73 passed, 3 subtests passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `git diff --check`: PASS.

Final Worker verification before freeze:

- `pytest`: 73 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

M4-C freeze:

- qualified commit: `2c232fa163c67d8af87e3d039affd11187a5c814`.
- qualified tag: `m4c-qualified`.
- qualified tag object: `256cdd6348dc76c05a92dc33d602ee691498ab5c`.
- post-freeze Git state: local `master` is 3 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M4-D Specification Freeze

M4-D is frozen as lightweight digest History backed by durable run identities and persisted run snapshots where available.

The History view must show completed/failed digest runs and persisted digest/synthesis snapshots without recomputing historical results from current settings.

The detailed frozen specification is maintained in `docs/campaigns/release1/CAMPAIGN_STATE.md`.

## M4-D Candidate

Implementation summary:

- Added `run_snapshots` storage keyed by durable `app_runs.id`.
- Added `research_digest.history` for immutable snapshot construction, snapshot persistence, bounded run listing, and detail loading.
- Successful per-profile service runs persist snapshots only after a valid digest and synthesis are available.
- Failed runs retain sanitized `app_runs.error_message` and do not create fabricated snapshots.
- Added a History Streamlit page and navigation entry.

Deterministic verification:

- `pytest`: 94 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Focused coverage added:

- completed digest run writes a snapshot linked to run id.
- failed run appears in history with sanitized error and no snapshot.
- current profile changes do not mutate historical snapshots.
- bounded history limit.
- History navigation exists.

Live verification:

- Isolated successful and failed history smoke using deterministic fake source/analyzer and temporary SQLite DB passed:
  `pytest tests/test_history.py::HistoryTests::test_completed_digest_run_writes_history_snapshot tests/test_history.py::HistoryTests::test_failed_run_has_sanitized_history_without_snapshot -q`.

Audit status:

- Fresh independent M4-D Auditor returned PASS with no BLOCKER/IMPORTANT findings.
- Auditor verified durable `app_runs` identity, immutable run snapshots, failed-run handling without fabricated snapshots, unavailable-snapshot display for older rows, History navigation, no M6-style memory/search/timelines, and full deterministic gates.

Auditor verification:

- full `pytest -q -p no:cacheprovider`: 94 passed, 9 subtests passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- independent temp-DB probe for legacy status normalization and snapshot absence/presence: PASS.

M4-D freeze:

- qualified commit: `ee280f439b9df3d5478779e33dd55995dabcc9fc`.
- qualified tag: `m4d-qualified`.
- qualified tag object: `0ae15c90d886fd9d03c3cf8d3c4f519fc57b5955`.
- post-freeze Git state: local `master` is 4 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-A Specification Freeze

M7-A is frozen as the release-critical separation of replaceable code from persistent user configuration and data.

Default SQLite storage must move to a platform user data directory, while explicit `RESEARCH_DIGEST_DB` remains supported. Existing repo-local M2 databases must be safely adopted by copy when no user-data DB exists and must never be silently overwritten.

The detailed frozen specification is maintained in `docs/campaigns/release1/CAMPAIGN_STATE.md`.

## M7-A Candidate

Implementation summary:

- Default SQLite DB path now resolves to a platform user data directory using standard-library OS conventions.
- Config directory resolves separately for later versioned configuration work.
- Explicit `RESEARCH_DIGEST_DB` remains authoritative and disables legacy DB adoption.
- Legacy repo-local DB adoption copies into user data only when the target user-data DB is missing.
- Existing user-data DB is never overwritten by legacy adoption.
- Codex analyzer construction no longer initializes app DB/data directories.

Deterministic verification:

- `pytest`: 97 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Focused coverage added:

- isolated user data/config directory resolution.
- explicit DB override is respected and disables adoption.
- legacy DB copy/adoption when user-data DB is missing.
- existing user-data DB is not overwritten by legacy DB.
- scheduler request construction uses active DB path.

Live verification:

- Isolated adoption smoke using temporary DB copies passed:
  `pytest tests/test_config.py::ConfigTests::test_legacy_db_is_adopted_when_user_data_db_is_missing tests/test_config.py::ConfigTests::test_existing_user_data_db_is_not_overwritten_by_legacy_db tests/test_config.py::ConfigTests::test_explicit_db_path_is_respected_and_disables_adoption -q`.

Audit status:

- Fresh independent M7-A Auditor returned FAIL with one IMPORTANT finding.

Initial audit findings:

- Legacy DB adoption was not failure-safe because copy went directly to the final DB path; an interrupted copy could leave a partial DB accepted on the next startup.
- MINOR: M7-A freeze criteria still referenced M4-D/`m4d-qualified`.
- MINOR: `OpenAIAnalyzer(api_key=..., model=...)` still called full app config and could trigger DB adoption as a constructor side effect.

Repair round 1:

- Legacy adoption now copies to a temporary file, validates SQLite integrity, then atomically replaces the target.
- Invalid partial active DBs are repaired from a valid legacy DB or fail closed if no valid legacy DB exists.
- `OpenAIAnalyzer` reads only explicit/env OpenAI API settings and no longer initializes app DB/data paths during construction.

Repair verification:

- focused M7-A config/scheduler/CLI/provider tests: 27 passed.
- targeted `ruff check`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- full `pytest`: 99 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Audit status:

- Fresh independent M7-A re-auditor returned PASS with no BLOCKER/IMPORTANT findings.
- Re-auditor verified failure-safe adoption, partial DB repair/fail-closed behavior, explicit DB override, provider no-adoption behavior, scheduler active DB path, ignored runtime state, full deterministic gates, and independent temporary probes.

Re-auditor verification:

- focused pytest: 26 passed, 6 subtests passed.
- full `pytest`: 99 passed, 9 subtests passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check m4d-qualified --`: PASS.
- independent temp probes: interrupted adoption repair PASS; provider no-adoption PASS; scheduler active DB path PASS; M2-era style DB adoption PASS.

M7-A freeze:

- qualified commit: `62d6ed4a3902a929d94d6612edc74af0a18cd7a1`.
- qualified tag: `m7a-qualified`.
- qualified tag object: `7a8e3da4ffa79570b5d6748f43a2a586a2268b5e`.
- post-freeze Git state: local `master` is 5 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-B Specification Freeze

M7-B is frozen as explicit versioned SQLite schema migrations with migration backups and failure-safe upgrade behavior.

The implementation must persist schema version, apply ordered deterministic migrations, back up before schema-changing upgrades, fail without destroying the previous usable DB, and validate fresh/current/M2-era/failed-upgrade paths.

The detailed frozen specification is maintained in `docs/campaigns/release1/CAMPAIGN_STATE.md`.

## M7-B Candidate

Implementation summary:

- Added durable SQLite schema metadata with `CURRENT_SCHEMA_VERSION`.
- Replaced startup schema setup with a small ordered `SchemaMigration` sequence.
- Preserved legacy M2-era repairs for relevance-analysis profile fingerprints and app-run preselection counters as ordered migrations.
- Added recoverable SQLite backup creation before schema-changing upgrades of existing unversioned/older databases.
- Exposed schema version and last migration backup path through the database boundary.
- Added migration failure handling that rolls back active DB mutations and raises `MigrationError` with the backup path.

Deterministic verification:

- `pytest`: 103 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live/data-safety verification:

- isolated M2-era style SQLite upgrade smoke passed using a temporary database copy.
- upgraded database and migration backup both passed SQLite `PRAGMA integrity_check = ok`.
- repo-local `research_digest.sqlite3` was not used for upgrade testing.

Audit:

- fresh independent read-only M7-B Auditor: PASS with no BLOCKER/IMPORTANT findings.
- auditor MINOR about stale freeze-criteria wording in `CAMPAIGN_STATE.md` was repaired before freeze.

Data-safety note:

- During re-audit, the auditor reported one accidental manual CLI smoke without `RESEARCH_DIGEST_DB`; it likely wrote one runtime run record to ignored repo-local `research_digest.sqlite3`.
- The repository worktree and staged inventory are unaffected.
- A content-free SQLite `PRAGMA integrity_check` against the ignored repo-local DB returned `ok`.

M4-A freeze:

- qualified commit: `82b8a7e82c047c9dff96d075f7f8b9981fa9f312`.
- qualified tag: `m4a-qualified`.
- qualified tag object: `99a1d7388903f11ef678b528d0879c7d33c25044`.
- post-freeze Git state: local `master` is 1 commit ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M4-B Specification Freeze

M4-B is frozen as Windows Task Scheduler support from WSL2 through a small scheduling backend and `research-digest schedule` CLI group.

The scheduled task must invoke the M4-A headless target, not Streamlit:

`wsl.exe -d <distro> --cd <working-dir> --exec env RESEARCH_DIGEST_DB=<absolute-db-path> research-digest run`

Windows daily triggers are defined in Windows local time and follow Windows daylight-saving behavior. That behavior must be visible in install/status output and tests.

PowerShell interop probe:

- `powershell.exe` exists at `/mnt/c/windows/System32/WindowsPowerShell/v1.0/powershell.exe`.
- Running `powershell.exe -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'` fails in this session with `WSL ... UtilBindVsockAnyPort ... socket failed 1`, including after sandbox escalation.
- This is recorded as an environment-blocked live Task Scheduler smoke unless later interop probes succeed.

## M4-B Candidate

Implementation summary:

- Added `research_digest.scheduler` with a Windows Task Scheduler backend and a typed `SchedulerBackend` boundary.
- Added schedule request/status/result models so future cron/systemd/launchd backends can be additive.
- Added deterministic construction of the scheduled WSL action:
  `wsl.exe -d <distro> --cd <working-dir> --exec env ... research-digest run`.
- Tightened install-time executable handling so the backend resolves the Windows `wsl.exe` path and the installed `research-digest` command. If `research-digest` is not on PATH, schedule install fails clearly rather than creating a broken task.
- Scheduled environment includes non-secret runtime settings such as `RESEARCH_DIGEST_DB`, provider choice, and non-secret model/timeout values; it excludes `OPENAI_API_KEY` and Codex auth material.
- Added `research-digest schedule status`, `research-digest schedule install --time HH:MM`, and `research-digest schedule remove`.
- Install uses `Register-ScheduledTask -Force`; remove treats a missing task as a successful not-installed result.
- README now documents headless and WSL2 scheduling commands.

Deterministic verification:

- `pytest`: 85 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Focused coverage added:

- time validation for Windows local `HH:MM` schedule input.
- WSL distro, working directory, and DB path resolution.
- installed command and Windows `wsl.exe` resolution, including clear failure if `research-digest` is unavailable.
- scheduled command excludes API keys/secrets.
- idempotent mocked install/update/remove/status PowerShell behavior.
- CLI JSON and human schedule output.
- sanitized schedule failure output.

Live verification:

- `python -m research_digest.cli schedule status --task-name 'Research Digest Codex Smoke' --json` returns a sanitized Windows interop failure: `UtilBindVsockAnyPort ... socket failed 1`.
- Retrying the same CLI smoke after sandbox escalation returns the same failure.
- No Task Scheduler task was installed, triggered, or removed in this session.

Audit status:

- Fresh independent M4-B Auditor requested.

M4-B audit and freeze:

- Fresh independent M4-B Auditor returned PASS with no BLOCKER/IMPORTANT findings.
- Auditor verified scheduler boundary separation, Windows Task Scheduler backend behavior, stable scheduled `research-digest run` target, secret exclusion, status visibility, README timezone/DST documentation, deterministic tests, and environment-blocked live Task Scheduler smoke.
- qualified commit: `9d7db2ce0983e8fa1a68534450b890ae110ebed8`.
- qualified tag: `m4b-qualified`.
- qualified tag object: `2c204f177d7ace500766365fc49d780ad08d8ceb`.
- post-freeze Git state: local `master` is 2 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M4-C Specification Freeze

M4-C is frozen as robust run lifecycle semantics using SQLite-local exclusion and stale recovery over the existing `app_runs` model.

The implementation must prevent unsafe overlap for manual/scheduled headless runs, make failures terminal and sanitized, support retry after failure, recover stale/crashed runs after a finite timeout, and preserve M2 cache reuse on repeated unchanged runs.

The detailed frozen specification is maintained in `docs/campaigns/release1/CAMPAIGN_STATE.md`.

## M4-C Candidate

Implementation summary:

- Added a SQLite-local `run_locks` table and atomic lock acquisition through `BEGIN IMMEDIATE`.
- New app runs use explicit lifecycle statuses: `STARTING`, `RUNNING`, `COMPLETED`, `FAILED`, and `ANALYSIS_UNAVAILABLE`.
- Stale lock recovery marks stale unfinished `STARTING`/`RUNNING` rows failed with a sanitized local message; legacy lowercase `running` rows are recognized for compatibility.
- `run_digest_for_profile` and `run_digest_for_enabled_profiles` acquire the shared digest lock; multi-profile headless runs hold one lock across the whole batch.
- Existing M2 cache/reuse remains delegated to `run_digest`.
- Failed runs release locks in `finally`, allowing retry after failure.

Deterministic verification:

- `pytest`: 89 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Focused coverage added:

- simultaneous service run exclusion.
- stale/crashed lock recovery and stale running-row terminal failure.
- failed run records sanitized terminal failure.
- retry after failure succeeds.
- repeated unchanged run reuses M2 analysis cache.
- batch run releases lock after per-profile failure.
- SQLite `PRAGMA integrity_check` after failed/retry/repeated runs.

Live verification:

- Isolated overlap/stale lifecycle smoke using deterministic fake source/analyzer and temporary SQLite DB passed:
  `pytest tests/test_run_lifecycle.py::RunLifecycleTests::test_simultaneous_service_runs_are_excluded tests/test_run_lifecycle.py::RunLifecycleTests::test_stale_lock_and_running_row_recover_to_failed -q`.

Audit status:

- Fresh independent M4-C Auditor returned FAIL with two IMPORTANT findings.

Initial audit findings:

- Stale lock recovery could leave an old run stuck as `RUNNING` if the run row started after the stale lock timestamp.
- Legacy app run statuses were not normalized at the `get_app_runs` read boundary.

Repair round 1:

- Stale-lock replacement now marks all unfinished `STARTING`/`RUNNING`/legacy `running` rows failed, because the stale lock is the crashed-run authority.
- Startup cleanup without an existing lock still marks only unfinished rows older than the stale cutoff.
- `get_app_runs` now normalizes legacy `running`, `success`, `failed`, and `analysis_unavailable` statuses in SQL.
- Regression tests cover both auditor probes.

Repair verification:

- focused `pytest tests/test_db.py::DatabaseTests::test_legacy_app_runs_gain_preselection_count_columns tests/test_run_lifecycle.py::RunLifecycleTests::test_stale_lock_and_running_row_recover_to_failed`: 2 passed.
- `ruff check src/research_digest/db.py tests/test_db.py tests/test_run_lifecycle.py`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- full `pytest`: 89 passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Audit status:

- Fresh independent M4-C re-auditor returned PASS with no BLOCKER/IMPORTANT findings.
- Re-auditor verified stale-lock replacement, legacy status normalization, service-level lock coverage, explicit lifecycle transitions, sanitized failure, overlap/stale/retry/cache/DB-integrity coverage, and full deterministic gates.

Re-auditor verification:

- Focused lifecycle/legacy tests: 5 passed.
- Independent temp-DB stale-lock and legacy-normalization probes: PASS.
- full `pytest -q -p no:cacheprovider`: 89 passed, 9 subtests passed.
- `ruff check .`: PASS.
- strict `mypy --no-incremental src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.
