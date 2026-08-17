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

## Restored Release Campaign Charter

The human restored the missing release-campaign authority after recovery found that durable docs only defined M4-A through M4-D and M7-A through M7-G. The restored authority is now recorded durably in `CAMPAIGN_STATE.md` and governs the remaining campaign.

Operational model:

- supervised autonomous Worker/Auditor campaign;
- persistent Worker implementation/repair;
- fresh independent read-only Auditor for each remaining substage;
- bounded audit-repair loop: initial candidate plus up to two audit-driven repair rounds per substage;
- deterministic gates and live/runtime smoke tests where appropriate;
- durable state/report updates at meaningful boundaries;
- local commits and local annotated tags only after qualification.

Commit/tag authority:

- The human explicitly authorizes local staging, local commits, and local annotated qualification tags for qualified M7-G, M7-H, M7-I, and release-candidate closeout bookkeeping.
- The campaign must not push, create a final public release/version tag, publish a GitHub release, publish a package, or perform a final public release without the final human release decision.

Remaining substages:

- M7-G: backup/export qualification and `m7g-qualified`.
- M7-H: release UI and installation polish without M3/M5/M6 functionality, then `m7h-qualified`.
- M7-I: release qualification matrix and packaging/install/upgrade/operate evidence, then `m7i-qualified`.
- Final release-candidate gate: release materials, final complete verification, final Auditor over the delta from `m2-qualified`, local closeout bookkeeping, then `RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN`.

Human stop:

- Stop only for material ambiguity, frozen-contract changes, weakened security/permission boundaries, new paid/external service or credential needs, unsafe/ambiguous repository or data recovery state, materially contradictory Worker/Auditor evidence after inspection and testing, exhausted audit-repair budget, or the final release-candidate gate.
- Do not stop for ordinary test failures, Streamlit failures, SQLite migration/backup failures, malformed Codex output, scheduling failures, packaging failures, or ordinary Auditor BLOCKER/IMPORTANT implementation findings; those remain inside the repair loop.

Scope boundary:

- M3 RSS/Atom/general feeds, arbitrary HTML extraction, and additional source pools are out of scope.
- M5 full-paper/PDF deep reading is out of scope.
- M6 embeddings/vector memory, long-term semantic trend analysis, and research-question memory are out of scope.
- Redis, Celery, distributed services, Kubernetes, authentication/multi-user systems, cloud requirements, vector databases, and generic agent frameworks are out of scope.
- The release remains a small, local-first, upgradeable arXiv research-digest application.

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

M7-B freeze:

- qualified commit: `73b549a75d372ad754f2a90f5c6aae788c7434fa`.
- qualified tag: `m7b-qualified`.
- qualified tag object: `ad09bde4eb4a6103e147e729c4bb0024d6bd19a6`.
- post-freeze Git state: local `master` is 6 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-C Specification Freeze

M7-C is frozen as additive stable extension boundaries, not implementations of postponed feature campaigns.

The implementation must preserve M1/M2/M4/M7-A/M7-B behavior while formalizing small typed boundaries for source adapters, analyzer factories, preselection, synthesis, future content retrieval, future delivery, and future memory/history services.

M3, M5, and M6 remain post-release campaigns; this substage may only make them addable without rewriting the application.

## M7-C Candidate

Implementation summary:

- Added source definitions, a default source registry, and `SourceRunRequest` to carry source name, adapter, and source-specific config together.
- Generalized service/pipeline source execution around `SourceRunRequest[Any]`; arXiv remains the default configured release source.
- Added analyzer registry/factory support while preserving codex/openai behavior.
- Added a typed cross-paper synthesizer boundary and service injection point while preserving deterministic synthesis.
- Added import-only content reader, delivery, and memory protocols for future additive M5/M6 work.
- Added architectural regression tests proving default/additive source registry behavior, analyzer registry behavior, non-arXiv config flow through service/pipeline, alternate synthesis injection, and future protocol importability.

Deterministic verification:

- `pytest`: 108 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Audit:

- initial fresh independent M7-C Auditor: FAIL with one IMPORTANT source-boundary finding.
- repair round 1 generalized source execution through `SourceRunRequest[Any]` and added a non-arXiv source-config smoke.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT/MINOR findings.

M7-C freeze:

- qualified commit: `246b1fee3a983e5da88e54c8f67850d0a6d3fa4f`.
- qualified tag: `m7c-qualified`.
- qualified tag object: `1c8f5c66d3b0b217057f39af53a3e210288db0fd`.
- post-freeze Git state: local `master` is 7 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-D Specification Freeze

M7-D is frozen as versioned persisted configuration in the user config directory, with explicit environment overrides preserved.

The implementation must create/load/upgrade a small JSON config file with a durable `config_version`, reject unknown future versions, avoid persisting secrets, and keep semantic settings such as analyzer provider/model/timeout stable unless explicitly changed.

## M7-D Candidate

Implementation summary:

- Added a versioned JSON config file in the resolved user config directory.
- Added `CONFIG_VERSION = 1`, config path, and last config backup path metadata to `AppConfig`.
- Missing config initializes deterministic defaults without Streamlit.
- Version 0 config upgrades to version 1 with a `.bak-v0-to-v1` backup.
- Unknown future config versions fail clearly.
- Persisted config validates supported keys and semantic provider/model/timeout values.
- Persisted config rejects secret/API-key keys.
- Environment overrides remain explicit, validated, and non-mutating.

Deterministic verification:

- `pytest`: 116 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live/config verification:

- isolated config smoke initialized defaults, applied env override without file mutation, upgraded old config with backup, rejected a future config version, and rejected a persisted secret-key config.

Audit:

- initial fresh independent M7-D Auditor: FAIL with one IMPORTANT finding for unvalidated env model overrides.
- repair round 1 validates `OPENAI_MODEL` and `RESEARCH_DIGEST_CODEX_MODEL` env overrides with non-empty trimmed semantics.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT/MINOR findings.

M7-D freeze:

- qualified commit: `2c1f9feb5ca95accf28527b0956727bb275642d0`.
- qualified tag: `m7d-qualified`.
- qualified tag object: `e02247e1796fab983d220916f6db73a8c7056ffd`.
- post-freeze Git state: local `master` is 8 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-E Specification Freeze

M7-E is frozen as the stable installed CLI surface for release operation.

The implementation must add `serve`, `status`, and `--version`, preserve `run` and schedule behavior, expose stable `doctor`/`backup` command slots for M7-F/M7-G, avoid business-logic duplication, and keep output free of secrets.

## M7-E Candidate

Implementation summary:

- Added `research-digest --version`.
- Added `research-digest serve` using `python -m streamlit run` against the installed UI entry point, with local port fallback and printed URL.
- Added `research-digest status` with text/JSON output for data path, config path, provider, schema/config versions, last run, and scheduler status.
- Preserved `run` and `schedule` behavior.
- Added stable deferred `doctor` and `backup` command slots for M7-F/M7-G.

Deterministic verification:

- `pytest`: 120 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live/CLI verification:

- `python -m research_digest.cli --version`: PASS.
- isolated temp-path `status --json`: PASS.
- mocked `serve --port 18501` fallback selected `http://localhost:18502`: PASS.

Audit:

- fresh independent read-only M7-E Auditor: PASS with no BLOCKER/IMPORTANT/MINOR findings.

M7-E freeze:

- qualified commit: `262bdd84be0c634c0b254e325c54304c0e840eb7`.
- qualified tag: `m7e-qualified`.
- qualified tag object: `5e46f46ec355391f7ee479d565855025cfa1db94`.
- post-freeze Git state: local `master` is 9 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-F Specification Freeze

M7-F is frozen as bounded, safe diagnostics through `research-digest doctor`.

The implementation must diagnose runtime, data/config paths, SQLite/schema/config versions, provider setup, Codex availability, scheduler status, last run health, and optional bounded network reachability without printing secrets or performing auto-repair.

## M7-F Candidate

Implementation summary:

- Added `research_digest.doctor` with typed check/report models and PASS/WARNING/FAILURE severities.
- Implemented safe diagnostics for runtime, data/config directories, SQLite integrity, schema/config versions, provider setup, scheduler status, last run health, and optional arXiv network reachability.
- Repaired doctor after audit so the real CLI path inspects config/data/SQLite state read-only instead of creating default config, adopting/migrating DBs, or writing migration backups.
- Repaired scheduler-originated doctor messages to sanitize status text as well as exceptions.
- Repaired doctor network timeout handling so non-finite, non-positive, or excessive values fail without invoking the network checker.
- Wired `research-digest doctor` text/JSON output plus `--network` and `--network-timeout`.
- Preserved `backup` as the deferred M7-G command slot.

Deterministic verification:

- focused post-repair `pytest tests/test_doctor.py tests/test_cli.py`: 18 passed.
- focused post-repair `ruff check src/research_digest/doctor.py src/research_digest/cli.py tests/test_doctor.py tests/test_cli.py`: PASS.
- focused post-repair strict `mypy --strict src/research_digest/doctor.py src/research_digest/cli.py tests/test_doctor.py tests/test_cli.py`: PASS.
- full post-repair `pytest`: 131 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live/doctor verification:

- isolated temp-path `doctor --json`: PASS without creating the configured data/config directories or SQLite DB.
- mocked network doctor smoke with finite timeout: PASS.

Audit:

- fresh independent M7-F Auditor returned FAIL with three IMPORTANT findings:
  real `doctor` initialized/migrated app state; scheduler status messages were not sanitized; invalid network timeouts such as `inf` were forwarded to network checks.
- repair round 1 addresses all three findings and adds regressions for read-only CLI doctor behavior, scheduler status redaction, direct invalid-timeout rejection, and CLI invalid-timeout usage errors.
- fresh independent M7-F repair round 1 re-auditor returned PASS with no BLOCKER/IMPORTANT findings.
- re-auditor verified focused and full deterministic tests, read-only temp CLI behavior, scheduler leak sanitization, and invalid timeout rejection before doctor execution.

M7-F freeze:

- qualified commit: `478f4d8582a2e3c9ad7b114fcfb4301253b1a961`.
- qualified tag: `m7f-qualified`.
- qualified tag object: `68746dba9d860cb53b3682ccc19d82b087411984`.
- post-freeze Git state: local `master` is 10 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-G Specification Freeze

M7-G is frozen as a user-facing backup/export feature through `research-digest backup`.

The implementation must create recoverable SQLite backups using SQLite's backup API, expose the generated backup path, optionally emit JSON, provide a portable JSON export of user-owned semantic data, exclude secrets/auth/local runtime material, and fail clearly for missing or invalid uninitialized databases without creating replacement state.

## M7-G Candidate

Implementation summary:

- Added `research_digest.backup` with a focused backup/export service.
- Implemented `research-digest backup` with `--json`, `--output`, and `--export-json`.
- SQLite backup uses a read-only source connection plus SQLite's backup API, writes through a temporary file, and validates the generated snapshot with `PRAGMA integrity_check`.
- Missing, invalid, non-file, or unsupported-schema databases fail clearly before output directories are created.
- JSON export sidecar includes profiles, source settings, feedback, app run summaries, and run snapshots, with sanitized persisted run errors and no environment/auth/local runtime material.

Deterministic verification:

- focused `pytest tests/test_backup.py tests/test_cli.py`: 12 passed.
- focused `ruff check src/research_digest/backup.py src/research_digest/cli.py tests/test_backup.py tests/test_cli.py`: PASS.
- focused strict `mypy --strict src/research_digest/backup.py src/research_digest/cli.py tests/test_backup.py tests/test_cli.py`: PASS.
- full `pytest`: 135 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live/backup verification:

- isolated real CLI smoke against a temp DB passed for `backup --json --output <tmp>/backups --export-json`.
- generated backup opened with SQLite `PRAGMA integrity_check = ok`.
- generated JSON export contained the expected profile and run data.

Audit:

- fresh independent M7-G Auditor requested.
- recovery after authentication renewal found the interrupted Auditor finding was not durably recorded in campaign docs.
- recovered status: HEAD remains `m7f-qualified`, M7-G candidate files are unstaged/uncommitted, no M7-G commit or tag exists, and no staged diff exists.
- reconstructed IMPORTANT finding: backup read-only SQLite URI handling is unsafe for DB paths containing SQLite URI-reserved characters such as `?` or `#`.
- Worker repair round 1 also includes a bounded backup hardening concern discovered before interruption: if `--export-json` derives a sidecar path that already exists, backup must fail before writing a new SQLite backup.
- repair round 1 uses escaped SQLite file URIs via `Path.as_uri()` and preflights the derived JSON export sidecar before any SQLite backup is written.
- repair round 1 regression coverage covers URI-reserved DB filenames and already-existing export sidecars.
- repair round 1 verification: focused `pytest tests/test_backup.py tests/test_cli.py` passed, 14 tests; focused `ruff` PASS; focused strict `mypy` PASS; full `pytest` passed, 137 tests; `ruff check .` PASS; strict `mypy --strict src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- repair round 1 live smoke passed against a temp DB path containing `?` and `#`; CLI backup/export exited 0, generated backup passed SQLite `PRAGMA integrity_check=ok`, and JSON export contained expected profile data.
- restored-charter pre-audit verification repeated the focused and full deterministic M7-G gates: focused backup/CLI tests 14 passed; full `pytest` 137 passed; `ruff check .` PASS; strict `mypy --strict src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- fresh independent M7-G repair round 1 closure Auditor returned PASS with no BLOCKER/IMPORTANT/MINOR findings.
- closure Auditor verified SQLite backup API/integrity validation, safe `Path.as_uri()` read-only SQLite URI handling, output collision/all-or-nothing preflight, missing/invalid DB behavior before output mutation, secret/privacy exclusion, CLI integration, Git hygiene, full deterministic gates, URI-reserved path smoke, and sidecar-collision preflight smoke.
- post-audit M7-G qualification gate passed: full `pytest` 137 passed; `ruff check .` PASS; strict `mypy --strict src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.

M7-G freeze:

- qualified commit: `4070cce4744fc0862e418b1db51f43019fb0a78c`.
- qualified tag: `m7g-qualified`.
- qualified tag object: `1a11880d39ba71aed06163620142eeca0aaa372f`.
- post-freeze Git state: local `master` is 11 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-H Specification Freeze

M7-H is frozen as release UI and installation polish for the already-qualified local-first arXiv research digest application.

The implementation must make the first-release Streamlit and documentation experience coherent without adding M3/M5/M6 functionality. Desired navigation is Today, History, Interests, Sources, and Settings. `research-digest serve` is the supported UI launch path. README/release-facing docs must guide ordinary users through installation, first run, Codex/ChatGPT authentication, optional OpenAI API provider, data/config locations, manual runs, UI launch, daily scheduling, backup, doctor, upgrades, known limitations, and release scope.

M7-H must preserve existing qualified service/config/CLI boundaries and avoid duplicating business logic in Streamlit.

## M7-H Candidate

Implementation summary:

- Added a Settings page to release navigation.
- Settings shows application/schema/config versions, data/config locations, analyzer provider status, doctor health summary, detailed doctor checks, and installed release commands.
- Added Material Symbols icons to Streamlit navigation.
- Improved Today first-run, no-provider/Codex-unavailable, and failure messages with sanitized actionable release copy.
- Rewrote README to use installed `research-digest` commands rather than raw Streamlit development launch commands.
- README now covers installation, first run, Codex/ChatGPT authentication, optional OpenAI API provider, data/config locations, manual digest, UI launch, daily scheduling, backup, doctor, upgrade expectations, known limitations, and M3/M5/M6 roadmap.

Deterministic verification:

- focused UI/docs tests: `pytest tests/test_ui_navigation.py tests/test_settings_page.py tests/test_release_docs.py tests/test_today_state.py` passed, 14 tests.
- focused UI/docs `ruff`: PASS.
- focused UI/docs strict `mypy`: PASS.
- full `pytest`: 139 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live/UI verification:

- `python -m research_digest.cli --version`: PASS, `research-digest 0.1.0`.
- temp-path `python -m research_digest.cli status --json`: PASS.
- `python -m research_digest.cli doctor --json`: PASS with sanitized warnings and no failures.
- direct `python -m research_digest.cli serve --port 18601` is blocked in this execution environment by local socket `Operation not permitted`; the same bind/connect restriction occurred after sandbox escalation during a port-conflict smoke. Deterministic CLI coverage verifies the `research-digest serve` command construction path, occupied-port fallback, and printed URL.

Audit:

- fresh independent read-only M7-H Auditor returned PASS with no BLOCKER/IMPORTANT/MINOR findings.
- Auditor verified Today/History/Interests/Sources/Settings navigation, first-run/no-provider/loading/failed/stale/empty/history states, Settings reuse of existing boundaries without business-logic duplication, README release CLI guidance and known limitations, no M3/M5/M6 feature implementation, Streamlit release hygiene, deterministic evidence, environment-limited serve smoke documentation, and Git hygiene.
- post-audit M7-H qualification gate passed: full `pytest` 139 passed; `ruff check .` PASS; strict `mypy --strict src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.

M7-H freeze:

- qualified commit: `e972d95933fc8145924883f0fa29cfeec52d4600`.
- qualified tag: `m7h-qualified`.
- qualified tag object: `4a1b6ab618265a15f9c99682e4d638583f362c32`.
- post-freeze Git state: local `master` is 12 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## M7-I Specification Freeze

M7-I is frozen as the release qualification matrix for installability, upgradeability, recoverability, and operability.

This is not a feature-development stage. It must build durable evidence for fresh install, upgrade from qualified M2 data, repeated startup, Codex unavailable, live Codex authenticated operation, network unavailable, scheduled headless run, overlap exclusion, application code upgrade, migration failure, backup, and serve/port conflict. It must also run deterministic and packaging gates including pytest, ruff, strict mypy, compileall, diff check, Git hygiene, package build/install, isolated fresh-venv installation, and installed CLI smokes.

## M7-I Candidate

Implementation/evidence summary:

- Added durable release qualification matrix: `docs/campaigns/release1/M7I_QUALIFICATION_MATRIX.md`.
- Added deterministic release qualification harness: `tests/test_release_qualification_matrix.py`.
- Harness covers fresh install-like config/DB/status initialization; representative unversioned/M2-style data adoption/migration; repeated startup without duplicate semantic data; backup/export from upgraded data; Codex-unavailable doctor behavior without secrets; sanitized bounded network failure; and serve port-conflict command construction.
- Matrix maps all twelve restored-charter cases to deterministic PASS evidence or exact environment-blocked live evidence.

Focused verification:

- `pytest tests/test_release_qualification_matrix.py`: 4 passed.
- `ruff check tests/test_release_qualification_matrix.py`: PASS.
- strict `mypy --strict tests/test_release_qualification_matrix.py`: PASS.

Initial package/install evidence:

- `python -m pip wheel . --no-deps -w /tmp/research-digest-wheelhouse`: blocked because PyPI DNS cannot resolve build dependency `hatchling`.
- Same wheel command after network escalation: same DNS failure.
- isolated fresh venv `pip install .`: blocked by the same `hatchling` DNS failure.
- Same fresh-venv install after network escalation: same DNS failure.
- Current development venv has editable `research-digest` version `0.1.0`.

Live/runtime evidence:

- `which codex`: PASS.
- `codex --version`: PASS, `codex-cli 0.147.0`.
- default `codex exec`: blocked by read-only default Codex home initialization.
- throwaway writable `CODEX_HOME` `codex exec`: blocked by OpenAI endpoint transport `Operation not permitted`.
- arXiv reachability probe: blocked by DNS failure, including after network escalation.
- schedule status: blocked by WSL Task Scheduler socket failure.
- direct serve listener: blocked by local socket `Operation not permitted`.
- temp-path `status --json`: PASS.
- `doctor --json`: PASS with sanitized environment warnings and no failures.
- `--version`: PASS, `research-digest 0.1.0`.

Full deterministic gate:

- full `pytest`: 143 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Initial M7-I audit:

- Fresh independent read-only M7-I Auditor `Meitner` returned FAIL with two BLOCKER findings.
- BLOCKER 1: installed CLI smoke evidence was missing and contradicted by the environment; no `research-digest` console script was available on PATH or in the development venv, and the candidate relied on `python -m research_digest.cli`.
- BLOCKER 2: the M2 upgrade harness did not use a copied/representative `m2-qualified` fixture; it created current-schema data through current APIs, dropped only `schema_metadata`, and therefore did not prove M2 upgrade preservation.

M7-I repair round 1:

- Replaced the external `hatchling` build backend with repo-local `_research_digest_build`, a minimal pure-Python PEP 517 backend for offline wheel construction and console-script metadata.
- Replaced the upgrade fixture with hand-built representative M2-qualified SQL containing profiles, source settings, articles, relevance analyses with profile fingerprints, feedback, app run history, and preselection counters, with no `schema_metadata` and no M4 run snapshots.
- The repaired harness verifies migration backup creation, schema version 4, count stability across repeated startup, M2 fingerprint preservation, and M7-G backup/export from the upgraded copied data.

M7-I repair round 1 focused evidence:

- `pytest tests/test_release_qualification_matrix.py`: 5 passed.
- `ruff check _research_digest_build.py tests/test_release_qualification_matrix.py pyproject.toml`: PASS.
- strict `mypy --strict tests/test_release_qualification_matrix.py`: PASS.
- `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-package.CtC0I9/wheelhouse`: PASS.
- isolated fresh-venv wheel install with `--no-deps`: PASS.
- installed wheel CLI `/tmp/research-digest-m7i-package.CtC0I9/venv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- installed entry point metadata query: PASS, `research_digest.cli:main`.
- installed wheel CLI `status --json` with isolated data/config from `/tmp`: PASS; schema version 4 and config version 1 initialized, scheduler warning sanitized.
- isolated fresh source install `pip install --no-deps .`: PASS.
- installed source CLI `/tmp/research-digest-m7i-package.CtC0I9/sourcevenv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.

M7-I repair round 1 full gate:

- full `pytest`: 144 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- package backend bytecode/cache repair: `_research_digest_build` now excludes `__pycache__` and `.pyc` files; harness asserts this.
- final current-state `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-finalpkg2.VfZt6V/wheelhouse`: PASS.
- final isolated fresh-venv wheel install with `--no-deps`: PASS.
- final installed CLI `/tmp/research-digest-m7i-finalpkg2.VfZt6V/venv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- final installed entry point metadata query: PASS, `research_digest.cli:main`.
- final installed CLI `status --json` with isolated data/config from `/tmp`: PASS; schema version 4 and config version 1 initialized, scheduler warning sanitized.
- final wheel-content cache/bytecode check: PASS, no `__pycache__` or `.pyc` members.

M7-I closure audit:

- Fresh independent read-only M7-I Auditor returned FAIL after verifying the two previous M7-I BLOCKERs were closed.
- IMPORTANT finding: the repo-local PEP 517 backend did not support the README-documented editable/dev install command `pip install -e ".[dev]"`, and generated package metadata omitted the `dev` extra.

M7-I repair round 1 installability follow-up:

- Added PEP 660 editable hooks to `_research_digest_build`.
- Added package metadata emission for optional extras: `Provides-Extra: dev` and extra-scoped `Requires-Dist` entries for `mypy`, `pytest`, and `ruff`.
- Added deterministic regression coverage for wheel metadata, bytecode/cache exclusion, and the documented editable install command.

M7-I repair round 1 second full gate:

- focused `pytest tests/test_release_qualification_matrix.py`: 6 passed.
- focused `ruff check _research_digest_build.py tests/test_release_qualification_matrix.py pyproject.toml`: PASS.
- focused strict `mypy --strict tests/test_release_qualification_matrix.py`: PASS.
- full `pytest`: 145 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- final current-state `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-finalpkg3.RhYfM6/wheelhouse`: PASS.
- final wheel metadata/content check: PASS, no generated bytecode/cache files; console script entry point present; `dev` extra metadata present.
- final isolated wheel install with `--no-deps`: PASS.
- final installed wheel CLI `/tmp/research-digest-m7i-finalpkg3.RhYfM6/wheelvenv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- final installed wheel CLI `status --json` with isolated data/config from `/tmp`: PASS; schema version 4 and config version 1 initialized, scheduler warning sanitized.
- final documented editable install `pip install -e '.[dev]' --no-deps`: PASS.
- final editable installed CLI `/tmp/research-digest-m7i-finalpkg3.RhYfM6/editablevenv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.

M7-I second closure audit:

- Fresh independent read-only M7-I Auditor returned PASS with no BLOCKER/IMPORTANT/MINOR/OPTIONAL findings.
- Auditor independently verified closure of the original installed-CLI and M2-upgrade BLOCKERs.
- Auditor independently verified closure of the editable/dev install IMPORTANT finding, including PEP 660 backend support, generated `dev` extra metadata, isolated wheel install, isolated editable install, and installed CLI smokes from `/tmp`.
- Auditor judged the full twelve-case M7-I matrix credible, with live Codex/arXiv/scheduler/serve gaps honestly documented as environment-blocked and acceptable for M7-I if carried into final release-candidate materials.

M7-I freeze:

- post-audit full `pytest`: 145 passed.
- post-audit `ruff check .`: PASS.
- post-audit strict `mypy --strict src tests`: PASS.
- post-audit `python -m compileall -q src tests`: PASS.
- post-audit `git diff --check`: PASS.
- qualified commit: `efc4c88a689d06dc0e4b4428605c05836ddb7374`.
- qualified tag: `m7i-qualified`.
- qualified tag object: `ec016b565fe84857b8053c51822290025b50c0db`.
- post-freeze Git state: local `master` is 13 commits ahead of `origin/master`; online remote inspection remains blocked by DNS/network limits in this session.

## Release-Candidate Gate

Release-candidate materials prepared:

- `docs/campaigns/release1/RELEASE_CANDIDATE_PACKET.md`.
- `docs/campaigns/release1/FINAL_RELEASE_CANDIDATE_VERIFICATION.md`.

Versioning state:

- `pyproject.toml` package version: `0.1.0`.
- `src/research_digest/__init__.py` runtime version: `0.1.0`.
- no existing public-style `v*` tags found.
- suggested human-reviewed public release tag: `v0.1.0`.

Final deterministic verification:

- full `pytest`: 145 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- targeted recovery/cache/migration/backup slice: 51 passed.

Final package/install evidence:

- `python -m pip wheel . --no-deps -w /tmp/research-digest-rc.Q4O1FA/wheelhouse`: PASS.
- wheel content/metadata checks: PASS, no `__pycache__`/`.pyc`, `dev` extra present, console entry point present.
- isolated wheel install with `--no-deps`: PASS.
- isolated editable install `pip install -e '.[dev]' --no-deps`: PASS.
- installed wheel CLI `--version`: PASS, `research-digest 0.1.0`.
- installed editable CLI `--version`: PASS, `research-digest 0.1.0`.
- installed wheel CLI `status --json`: PASS, schema version 4 and config version 1 initialized.
- installed wheel CLI `doctor --json`: PASS with no failures before live failed-run smoke.

Final live/runtime evidence:

- disposable profile/source configured in isolated data/config under `/tmp/research-digest-rc.Q4O1FA`.
- installed `research-digest run --json`: FAIL with sanitized arXiv DNS error; same after escalation.
- status after live attempts: PASS, failed run recorded and DB valid.
- `doctor --json --network --network-timeout 5`: FAIL only because last run failed; network warning records arXiv DNS failure; same after escalation.
- `which codex`: PASS.
- `codex --version`: PASS, `codex-cli 0.147.0`.
- minimal Codex model probe with writable `CODEX_HOME`: FAIL after bounded retries due OpenAI websocket/HTTPS transport errors; same after escalation.
- `research-digest schedule status --json`: FAIL with sanitized WSL Task Scheduler socket error.
- `research-digest serve --port 18601`: FAIL with sanitized local socket `Operation not permitted`; same after escalation.
- `research-digest backup --json --export-json`: PASS.
- backup `PRAGMA integrity_check`: `ok`.
- JSON export validates and contains no secrets/authentication material.

Final hygiene evidence:

- no tracked `.env`, SQLite DB, virtualenv, cache, `.codex`, or `.codegraph` paths.
- secret-pattern scan found only fake redaction-test strings and known documentation references; no real credentials or runtime auth material.
- no public release tag, push, GitHub release, package publication, or public release operation performed.

Final release audit:

- fresh independent final release Auditor over `m2-qualified..f8d87eda5048c111d5d754c2e089ef3a33254508`: PASS WITH MINOR FINDINGS.
- MINOR: release bookkeeping pointed at the M7-I base rather than the actual RC commit.
- MINOR: README/human-packet upgrade backup instructions needed clearer sequencing for older repo-local M2 development databases.

Final-audit MINOR follow-up:

- corrected CAMPAIGN_STATE and final verification docs to distinguish the M7-I qualified base from the actual release-candidate commit.
- clarified README and release-candidate packet upgrade instructions: back up an already-current active DB with `research-digest backup --export-json`; for an older repo-local M2 database, first keep a separate copy of the SQLite file, let startup adopt/migrate the copied legacy DB and create the pre-migration backup, then use `research-digest backup --export-json` against the current active DB after migration.
- final release-candidate commit after MINOR follow-up: `eadedb71b7a64302edb6ac6b7d1fbfe1d6bfbe95`.
- final campaign state set to `RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN`; no public release tag, push, GitHub release, package publication, or public release operation was performed.
- that prior human-stop state was later reopened only for the live scheduler environment repair below; the prior RC commit is superseded pending repair audit, local repair commit, and human live scheduler smoke.

## Release-Candidate Scheduler Environment Repair

Live finding:

- interactive WSL resolved Codex at `/home/inaeyk/.nvm/versions/node/v22.22.2/bin/codex` and `codex login status` reported ChatGPT login.
- manual installed-CLI execution completed a subscription-backed Codex digest on new papers.
- the Windows Task Scheduler action ran WSL in a non-login environment whose `PATH` did not include the NVM directory containing Codex.
- the scheduled smoke produced `ANALYSIS_UNAVAILABLE` and Windows Task Scheduler `LastTaskResult: 1`.

Repair:

- Codex-backed `research-digest schedule install` now resolves the interactive `codex` executable and records its containing directory in scheduled `PATH` ahead of the normal minimal WSL system path.
- The scheduled task continues to preserve `HOME` by not overriding it and does not embed API keys, Codex tokens, copied auth files, or shell startup-file sourcing.
- Missing Codex during Codex-backed schedule installation fails clearly.
- `research-digest doctor` warns when an installed Codex-backed task lacks the current Codex executable directory, so reinstalling/updating the schedule can refresh stale Node/Codex paths.
- Added deterministic regression coverage for NVM-like paths, safe quoting, secret exclusion, missing-Codex failure, OpenAI-provider independence, and stale scheduler PATH warning.
- Added human live-smoke instructions in `docs/campaigns/release1/RC_SCHEDULER_LIVE_SMOKE.md`.

Repair qualification:

- full `pytest`: 149 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- fresh independent read-only scheduler repair Auditor: PASS with no BLOCKER or IMPORTANT findings.

Current stop:

- The repair is not final release acceptance.
- Final release-candidate acceptance remains blocked until the human live scheduler smoke verifies the reinstalled/updated Windows task action, a new `COMPLETED` scheduled run, `LastTaskResult == 0`, and no secrets in the task action.

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
