# Release 1 Campaign State

- current_substage: M7-A candidate audit
- status: ACTIVE
- current_git_head: ee280f439b9df3d5478779e33dd55995dabcc9fc
- current_tags_at_head: m4d-qualified
- current_branch: master
- local_remote_tracking: `master` tracks `origin/master`; local branch is 4 commits ahead after M4-D freeze
- online_remote_verification: attempted `git ls-remote --heads --tags origin`; blocked by DNS resolution failure for `github.com` even after network escalation
- baseline_m1_qualified_commit: 36bd1cbe60f95d588e8ccdd41bfce914e9b1d7da
- baseline_m1_qualified_tag: m1-qualified
- baseline_m1_qualified_tag_object: be28fdfc5512e8d38a79956161407fef9a87eca4
- baseline_m2_qualified_commit: 8861682832aea1c5cd7dd3d580adecd98cd809a5
- baseline_m2_qualified_tag: m2-qualified
- baseline_m2_qualified_tag_object: 44ad1f4bd1c7bbaf09d9b430e6b16693ff8d9536
- baseline_m2a_qualified_commit: 81d4d5e011c46650c6094db628668e82a030547e
- baseline_m2b_qualified_commit: 9aea33b0a1dc8a2b34ad7622e55bb8fb047852bb
- baseline_m2c_qualified_commit: f6cbe703ae41657120105237fab221f56c2dc9e4
- baseline_m2d_qualified_commit: 1626793ef693fec068a1fa571a40d07c9ffb5233
- m4a_qualified_commit: 82b8a7e82c047c9dff96d075f7f8b9981fa9f312
- m4a_qualified_tag: m4a-qualified
- m4a_qualified_tag_object: 99a1d7388903f11ef678b528d0879c7d33c25044
- m4b_qualified_commit: 9d7db2ce0983e8fa1a68534450b890ae110ebed8
- m4b_qualified_tag: m4b-qualified
- m4b_qualified_tag_object: 2c204f177d7ace500766365fc49d780ad08d8ceb
- m4c_qualified_commit: 2c232fa163c67d8af87e3d039affd11187a5c814
- m4c_qualified_tag: m4c-qualified
- m4c_qualified_tag_object: 256cdd6348dc76c05a92dc33d602ee691498ab5c
- m4d_qualified_commit: ee280f439b9df3d5478779e33dd55995dabcc9fc
- m4d_qualified_tag: m4d-qualified
- m4d_qualified_tag_object: 0ae15c90d886fd9d03c3cf8d3c4f519fc57b5955
- skipped_campaigns: M3 additional source types; M5 full-paper reading; M6 long-term research memory
- active_campaign_scope: M4 automatic daily operation; M7 release engineering, upgradeability, and productization; first release candidate
- qualification_status: M7A_REAUDIT_PASS_READY_FREEZE
- audit_repair_round: 1
- last_deterministic_verification: M7-A repair round 1 full gate: `pytest` 99 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- last_live_verification: M7-A isolated adoption smoke `pytest tests/test_config.py::ConfigTests::test_legacy_db_is_adopted_when_user_data_db_is_missing tests/test_config.py::ConfigTests::test_existing_user_data_db_is_not_overwritten_by_legacy_db tests/test_config.py::ConfigTests::test_explicit_db_path_is_respected_and_disables_adoption -q` passed against temporary SQLite DB copies.
- migration_data_safety_status: no release1 migrations applied yet; repo-local `research_digest.sqlite3` remains ignored and must not be used for upgrade tests. During M4-A re-audit, a manual CLI smoke likely wrote one runtime run record to the ignored repo-local DB; a content-free `PRAGMA integrity_check` returned `ok`.
- deferred_minor_optional_findings: none
- next_permitted_action: perform freeze hygiene, commit, and tag `m7a-qualified`
- human_stop_reason: none

## M4-A Frozen Specification

Goal: provide headless execution of the complete qualified M2 digest workflow without importing or requiring Streamlit at run time.

Stable command target:

- Installed command concept: `research-digest run`
- Development fallback may use `python -m research_digest.cli run` until packaging is formalized in M7-E, but the application boundary must already be stable enough for the later installed command to call it without rewriting business logic.

Application/service boundary:

- Add a core service boundary outside `research_digest.ui`.
- Streamlit, CLI, and later scheduler code must call this boundary rather than duplicating pipeline logic.
- The boundary must preserve the source adapter and analyzer provider abstractions.
- The boundary must not introduce a generic workflow engine.

Run scope:

- A headless run processes every enabled interest profile.
- For this release baseline, the enabled source is the existing arXiv source configuration.
- Each enabled profile gets its own existing pipeline run identity through the current `run_digest` semantics.
- If no enabled profiles exist, the command exits deterministically with a non-zero status and sanitized human-readable error.
- If the arXiv source is disabled, the command still runs through the existing source configuration semantics and reports zero retrieved/analyzed work rather than requiring Streamlit.

Workflow coverage:

- retrieval
- article persistence
- two-stage abstract preselection
- relevance analysis with existing provider selection
- M2 cache/profile semantic reuse and invalidation
- persisted run history through `app_runs`
- feedback calibration summary over current run results
- cross-paper synthesis over current run results

Output:

- Default output is concise human-readable text summarizing per-profile run id, retrieved/stored/analyzed/relevant/new/reused/skipped counts, feedback count if available, and synthesis signal if available.
- Add a simple machine-readable option, `--json`, returning JSON with the same non-secret summary fields.
- Output must not include API keys, Codex auth material, personal interest descriptions, article abstracts, or SQLite row contents beyond non-sensitive counts/titles already visible in normal digest output only if needed. Prefer counts for M4-A.

Exit status:

- `0`: all selected profile runs completed without failure.
- `1`: deterministic user/config/runtime failure after sanitization, including missing enabled profiles, missing provider, source failure, or analyzer failure.
- `2`: command usage error.
- Future M4-C may refine overlap/lock-specific exit statuses.

Analyzer behavior:

- The default Codex CLI provider must remain usable without `OPENAI_API_KEY`.
- OpenAI API provider remains optional and must never hard-code keys.
- Provider errors must be sanitized before display and before persistence.

Tests required before M4-A freeze:

- headless service invokes existing pipeline once per enabled profile
- multiple enabled profiles produce separate run summaries
- disabled/no-profile behavior has deterministic exit/status
- `--json` output is valid and contains no secrets
- Codex provider construction path does not require `OPENAI_API_KEY`
- Streamlit Today remains backed by the same service or unchanged pipeline boundary without duplicated business logic
- existing M2 cache/reuse tests remain green

Live verification required before M4-A freeze:

- run a small headless command against the local configured environment using the Codex-backed provider when available
- if live Codex cannot run because of authentication/CLI/environment, record the sanitized failure and complete only if deterministic tests prove the provider boundary remains correct; do not weaken requirements

## M4-A Audit Log

- initial fresh Auditor: FAIL with one IMPORTANT finding. `research-digest run` returned exit `0` when the configured analyzer was unavailable, contrary to the frozen exit-status contract.
- repair round 1: CLI now treats analyzer unavailability as command failure (`exit 1`) while still allowing the underlying service/pipeline to persist the qualified `analysis_unavailable` run state. Focused tests updated accordingly and pass.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT findings. Re-auditor independently verified the analyzer-unavailable exit repair, no Streamlit import dependency for CLI/service/provider imports, shared UI/CLI service boundary, enabled-profile handling, M2 cache/reuse delegation, JSON privacy coverage, and Codex provider construction without `OPENAI_API_KEY`.
- freeze: committed `82b8a7e82c047c9dff96d075f7f8b9981fa9f312` (`Qualify M4-A headless execution`) and created local annotated tag `m4a-qualified` with tag object `99a1d7388903f11ef678b528d0879c7d33c25044`.

## M4-B Frozen Specification

Goal: allow automatic daily operation without Streamlit by installing an OS-backed schedule that invokes the qualified M4-A headless command.

Supported first-release backend:

- WSL2 on Windows through Windows Task Scheduler.
- Future Linux cron/systemd and macOS launchd support must be additive backend implementations, not digest-engine changes.
- The scheduling layer must be separate from `research_digest.service` and must not call pipeline code directly.

CLI surface:

- Add a small scheduling command group under `research-digest schedule`.
- Required operations for the Windows backend: `status`, `install`, `remove`.
- `install` is idempotent: if the named task exists, update it to the requested configuration.
- `remove` is idempotent: removing a missing task succeeds with an explicit not-installed result.
- `status` is inspectable and has a JSON option.

Resolved execution target:

- Scheduled task action must ultimately execute `wsl.exe -d <distro> --cd <working-dir> --exec env ... research-digest run`.
- Use the installed `research-digest` command as the stable target; do not schedule Streamlit or a Python source-file path.
- Resolve WSL distro from `WSL_DISTRO_NAME` unless explicitly overridden.
- Resolve working directory deliberately from the current repository path for this release. M7-A will move persistent data/config to platform user directories.
- Resolve data path deliberately. If `RESEARCH_DIGEST_DB` is set, schedule that absolute path. Otherwise schedule the current configured/default DB path as an absolute path.

Secrets and environment:

- Do not place `OPENAI_API_KEY`, Codex auth files, or other secrets in the task command.
- It is acceptable to set non-secret `RESEARCH_DIGEST_DB` and analyzer/provider selection variables needed to preserve runtime behavior.
- Codex saved ChatGPT authentication remains external to Research Digest and is not embedded in scheduler configuration.

Timezone and DST:

- Windows Task Scheduler daily triggers are interpreted in the Windows local timezone and follow Windows daylight-saving behavior.
- The CLI must document/report that behavior in schedule status/install output.
- Store requested local time as `HH:MM` and validate it deterministically.

Failure visibility:

- The scheduled command must invoke `research-digest run`; M4-A exit codes make failures visible to Task Scheduler LastTaskResult.
- Status must surface Task Scheduler state, last run time/result, and next run time when available.
- M4-C will add stronger durable run lifecycle/overlap semantics; M4-B must not implement a custom daemon or lock manager.

Tests required before M4-B freeze:

- command construction quotes/escapes arguments safely and excludes secrets
- WSL distro/data path/working directory resolution
- daily time validation and Windows local timezone/DST explanation
- install/update/remove/status idempotent behavior via mocked PowerShell runner
- unsupported non-WSL/Windows backend failure is clear and sanitized
- CLI status/install/remove JSON and human output are deterministic
- existing M4-A run and M2 deterministic tests remain green

Live verification required before M4-B freeze:

- If Windows interop is available, perform a real Task Scheduler smoke using a non-production test task name and a manual trigger/removal cycle.
- If PowerShell/Task Scheduler interop is blocked by this execution environment, record the exact sanitized failure and complete only if deterministic backend tests cover command generation and idempotent operations.

## M4-B Candidate Log

- implementation: added `research_digest.scheduler` with a Windows Task Scheduler backend, explicit schedule request model, WSL command construction, explicit `wsl.exe` and installed `research-digest` executable resolution, non-secret scheduled environment construction, time validation, status parsing, and idempotent install/remove behavior.
- CLI: added `research-digest schedule status|install|remove` with `--json`, task-name selection, backend selection, install time validation, and WSL distro override.
- docs: README documents `research-digest run` and WSL2 scheduling commands.
- self-review repair before audit completion: scheduler install now resolves the Windows `wsl.exe` executable and the installed `research-digest` command deliberately; if `research-digest` is not on PATH, install fails clearly instead of creating a broken schedule.
- deterministic verification: `pytest` 85 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live verification: Windows interop/Task Scheduler smoke is blocked in this session by `UtilBindVsockAnyPort ... socket failed 1`; CLI surfaces that as sanitized JSON failure. No scheduler task was created.
- fresh Auditor: PASS with no BLOCKER/IMPORTANT findings. Auditor verified the scheduler boundary is separate from the digest engine, Windows Task Scheduler backend behavior, stable `research-digest run` target, secret exclusion, status visibility, README timezone/DST documentation, deterministic tests, and environment-blocked live Task Scheduler smoke.
- freeze: committed `9d7db2ce0983e8fa1a68534450b890ae110ebed8` (`Qualify M4-B daily scheduling`) and created local annotated tag `m4b-qualified` with tag object `2c204f177d7ace500766365fc49d780ad08d8ceb`.

## M4-C Frozen Specification

Goal: automatic and manual execution cannot corrupt or duplicate work when runs fail, retry, repeat, or overlap.

Run lifecycle:

- Introduce explicit durable lifecycle states using the existing `app_runs` model: `STARTING`, `RUNNING`, `COMPLETED`, `FAILED`, plus `ANALYSIS_UNAVAILABLE` for the existing qualified analyzer-unavailable semantics.
- Preserve readable compatibility for existing M1/M2 rows whose statuses are `running`, `success`, `failed`, or `analysis_unavailable`; normalize them at read boundaries rather than rewriting historical rows unless a migration is required.
- Every new run must have a finite terminal status or be recoverable as stale/crashed.

Exclusion and stale recovery:

- Use SQLite-local locking; do not add Redis, queues, daemons, distributed locks, or external services.
- Scheduled and manual `research-digest run` invocations must not overlap unsafely.
- Use an atomic DB-backed run lock before workflow execution starts.
- If a lock is fresh, a competing invocation exits deterministically with a sanitized error and does not create duplicate work.
- If a lock is stale beyond a finite timeout, mark the stale run failed with a sanitized message and allow a new run.
- Default stale timeout should be conservative and configurable for tests without requiring user decisions.

Persistence and failure semantics:

- Partial provider/source failure must finish the associated run as `FAILED` and keep prior qualified data intact.
- Retry after failure must be supported by releasing/recovering the run lock.
- Repeated unchanged runs must continue to reuse M2 analysis cache semantics.
- Synthesis/calibration must only be computed from a completed per-profile digest result returned by the existing pipeline.
- Errors shown by CLI/UI and stored in DB must remain sanitized.

Scope constraints:

- Do not build a generic workflow engine.
- Do not change scheduler implementation except to rely on the M4-C-safe `research-digest run`.
- Do not redesign M2 article/analysis data or source/analyzer abstractions.
- M4-D will add user-facing History; M4-C only needs enough status data to make failed/running/stale runs durable and inspectable.

Tests required before M4-C freeze:

- simultaneous-run exclusion
- stale/crashed lock recovery
- failed run records terminal failure and sanitized error
- retry after failure succeeds
- repeated unchanged run preserves cache reuse
- database integrity after failed/retry/repeated runs
- existing M2/M4-A/M4-B deterministic tests remain green

Live verification required before M4-C freeze:

- run two headless invocations or service calls against an isolated DB to verify overlap exclusion deterministically
- run a stale-lock recovery smoke against an isolated DB
- if live Codex/network is unavailable, use deterministic fake analyzer/source for lifecycle smoke and record the Codex environment limit separately

## M4-C Candidate Log

- implementation: added SQLite-local `run_locks` table and DB lock acquire/release operations with stale recovery.
- lifecycle: new app runs now start as `STARTING`, move to `RUNNING`, and finish as `COMPLETED`, `FAILED`, or `ANALYSIS_UNAVAILABLE`.
- compatibility: stale recovery recognizes legacy lowercase `running` app rows while preserving existing historical data.
- service boundary: `run_digest_for_profile` and `run_digest_for_enabled_profiles` acquire a shared digest lock; multi-profile headless runs hold one lock for the full batch.
- failure/retry: service locks release in `finally`; failed profile runs remain terminal and sanitized, and later retries can proceed.
- deterministic verification: `pytest` 89 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live lifecycle smoke: isolated overlap exclusion and stale recovery tests passed against temporary SQLite DB.
- initial fresh Auditor: FAIL with two IMPORTANT findings. Stale lock recovery could leave a later-started old run row stuck as `RUNNING`, and `get_app_runs` did not normalize legacy lowercase statuses at the read boundary.
- repair round 1: stale-lock replacement now marks all unfinished `STARTING`/`RUNNING`/legacy `running` rows failed, because the lock itself is the stale/crashed authority. When no lock exists, startup cleanup still only marks unfinished rows older than the stale cutoff. `get_app_runs` now normalizes legacy `running`, `success`, `failed`, and `analysis_unavailable` statuses in its SELECT result. Regression tests cover both auditor probes.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT findings. Re-auditor verified stale-lock replacement, legacy status normalization, service-level lock coverage, explicit lifecycle transitions, sanitized failure, overlap/stale/retry/cache/DB-integrity coverage, and full deterministic gates.
- freeze: committed `2c232fa163c67d8af87e3d039affd11187a5c814` (`Qualify M4-C robust run semantics`) and created local annotated tag `m4c-qualified` with tag object `256cdd6348dc76c05a92dc33d602ee691498ab5c`.

## M4-D Frozen Specification

Goal: automatic operation is inspectable through lightweight digest run history.

History data boundary:

- History must correspond to durable `app_runs` identities.
- Show completed, failed, analysis-unavailable, running, and recovered-failed lifecycle states from the normalized run-status read boundary.
- Historical results must use persisted rows and must not rerun source retrieval, analyzer calls, calibration, or synthesis because current settings changed.
- Do not implement M6 memory: no semantic history search, topic timelines, long-term trend inference, embeddings, or vector store.

Persistence:

- Add the minimal durable storage needed to show a historical run's digest/synthesis where available.
- Store only local user-owned digest summary/synthesis data already produced by a run; no secrets or auth material.
- Prefer storing compact JSON snapshots keyed by `run_id`.
- Failed runs should display sanitized failure details from `app_runs.error_message`.
- Existing historical rows without snapshots must display counts/status and an explicit unavailable-snapshot state rather than mutating or recomputing.

UI:

- Add a Streamlit History view to release navigation.
- Show recent runs in reverse chronological order with date/time, status, profile/source, retrieved/analyzed/relevant counts, and sanitized failure summary when present.
- Selecting a historical run should show its persisted digest/synthesis snapshot where available.
- Use reasonable pagination or a bounded limit.
- Do not duplicate business logic in Streamlit; UI should call a non-UI history/query boundary.

Tests required before M4-D freeze:

- run history list maps normalized durable run statuses and counts
- completed digest run writes an immutable snapshot linked to run id
- failed run displays sanitized error and no fabricated snapshot
- current profile/source setting changes do not mutate historical snapshots
- pagination/limit behavior
- Streamlit History navigation exists
- existing M2/M4-A/M4-B/M4-C deterministic tests remain green

Live verification required before M4-D freeze:

- isolated headless run with fake source/analyzer creates a visible history entry and snapshot
- isolated failed run creates a visible failed history entry with sanitized error

## M4-D Candidate Log

- implementation: added `run_snapshots` table keyed by `run_id`, compact JSON snapshot persistence, and non-UI `research_digest.history` list/detail helpers.
- service boundary: successful per-profile digest runs persist snapshots after valid digest/synthesis creation; failed runs do not fabricate snapshots.
- UI: added Streamlit History navigation/page backed by the history helper module, with bounded run limit, status/count/error display, and persisted snapshot detail.
- immutability: tests verify current profile changes do not mutate prior snapshots.
- deterministic verification: `pytest` 94 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live history smoke: isolated successful and failed history-entry tests passed against temporary SQLite DB.
- fresh Auditor: PASS with no BLOCKER/IMPORTANT findings. Auditor verified durable `app_runs` identity, immutable run snapshots, failed-run handling without fabricated snapshots, unavailable-snapshot display for older rows, History navigation, no M6-style memory/search/timelines, and full deterministic gates.
- freeze: committed `ee280f439b9df3d5478779e33dd55995dabcc9fc` (`Qualify M4-D digest history`) and created local annotated tag `m4d-qualified` with tag object `0ae15c90d886fd9d03c3cf8d3c4f519fc57b5955`.

## M7-A Frozen Specification

Goal: separate replaceable application code from persistent user configuration and SQLite data.

Invariant:

- Code is replaceable.
- User data survives upgrades independently.
- Future code upgrades must not depend on preserving the source checkout.

User directories:

- Use platform-appropriate user directories for config and data.
- A small dependency such as `platformdirs` is allowed if it improves cross-platform correctness.
- Expose the active DB/data location through existing configuration/status surfaces where available.
- Tests must use isolated temporary directories and environment overrides.

Legacy DB adoption:

- Existing repo-local `research_digest.sqlite3` must not be lost.
- On first startup with no user-data DB and a legacy repo-local DB present, safely adopt it by copying to the user data directory.
- Never overwrite one existing DB with another silently.
- If both legacy and user-data DBs exist, prefer the explicit/user-data DB and leave the legacy DB untouched.
- If `RESEARCH_DIGEST_DB` is explicitly set, respect it and do not auto-adopt.

Runtime behavior:

- Default DB path should move from repo-local `research_digest.sqlite3` to user data directory.
- Config directory should be available for future versioned configuration in M7-D.
- Git repo runtime DB remains ignored.
- M4 scheduler must resolve the active DB path deliberately after this change.

Tests required before M7-A freeze:

- default DB path resolves to isolated user data dir under test override
- config dir resolves separately from data dir
- legacy repo-local DB is copied/adopted when no user-data DB exists
- existing user-data DB is never overwritten by legacy adoption
- explicit `RESEARCH_DIGEST_DB` disables adoption and is respected
- scheduler/build config uses the active DB path
- upgrade smoke with a copy of an M2-era DB
- existing M1/M2/M4 deterministic tests remain green

Live verification required before M7-A freeze:

- copy the ignored repo-local DB to a temporary legacy checkout path and verify adoption into a temporary user-data directory without modifying the original
- verify active data location output/path can be inspected without exposing DB contents

## M7-A Candidate Log

- implementation: default DB path now resolves to a platform user data directory using standard-library OS conventions, with a separate config directory resolver.
- compatibility: explicit `RESEARCH_DIGEST_DB` remains authoritative and disables legacy adoption.
- adoption: repo-local or explicitly supplied legacy DB is copied into user data when no user-data DB exists; existing user-data DB is never overwritten.
- provider hygiene: `CodexCLIAnalyzer` no longer calls full app config/DB-path setup just to read Codex model/timeout.
- scheduler: schedule requests use the active config DB path, so scheduled runs target the resolved user-data DB unless explicitly overridden.
- deterministic verification: `pytest` 97 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live adoption smoke: isolated legacy adoption, no-overwrite, and explicit-override tests passed against temporary DB copies.
- initial fresh Auditor: FAIL with one IMPORTANT finding. Legacy DB adoption copied directly to the final target path, so an interrupted copy could leave a partial DB accepted on the next startup. Auditor also noted MINOR stale M7-A freeze criteria wording and OpenAI provider DB-path side effect.
- repair round 1: legacy adoption now copies to a temporary file, validates SQLite integrity, and atomically replaces the target. Invalid partial active DBs are repaired from a valid legacy DB or fail closed. `OpenAIAnalyzer` no longer calls full app config/DB-path setup when explicit/env API settings are enough.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT findings. Re-auditor verified failure-safe adoption, partial DB repair/fail-closed behavior, explicit DB override, provider no-adoption behavior, scheduler active DB path, ignored runtime state, full deterministic gates, and independent temporary probes.

Freeze criteria:

- fresh independent read-only M7-A audit PASS
- `pytest`, `ruff check .`, `mypy --no-incremental src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m7a-qualified`
