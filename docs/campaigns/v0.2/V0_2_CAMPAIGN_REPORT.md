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

## U2-B Candidate

Implementation summary:

- Added `RunOrigin` and date-selection/coverage fields to `DigestResult`.
- Added optional `DateNativeSourceAdapter` protocol for source adapters.
- Wired `DateSelection` and `RunOrigin` through `run_digest`,
  `run_digest_for_profile`, and `run_digest_for_enabled_profiles`.
- Added schema version 5 with additive app-run metadata columns:
  `run_origin`, `date_selection_json`, requested/covered/empty/incomplete
  source-date JSON lists, retrieval completeness, and retrieval safety limit.
- Preserved legacy historical semantics by defaulting older rows to `LEGACY`
  origin and empty date metadata.
- Added date metadata to run snapshots, History entries, CLI status last-run
  payloads, and backup JSON export.

Behavior covered:

- Identical date rerun reuses cached article analyses.
- Different date selections produce distinct run metadata.
- Empty source dates complete with empty-date coverage.
- Partial retrieval cannot mark dates covered.
- Analyzer failure after retrieval records date metadata and retry succeeds.
- Historical snapshot date metadata remains immutable after current config
  changes.
- Legacy app-runs migrate with non-reinterpreting defaults.

Candidate deterministic verification:

- `pytest`: 172 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Audit status: fresh independent U2-B Auditor pending.

Initial independent U2-B Auditor:

- Auditor `01a00f95-797f-7bf1-ba94-bb43b2cf663a` returned FAIL with one
  IMPORTANT finding.
- Finding: source failures before date-retrieval metadata returned could persist
  `retrieval_complete=1` and empty requested/incomplete date lists.
- Repair round 1 precomputes deterministic requested dates for
  single/range/explicit selections, initializes date-native retrieval as
  incomplete until the source returns, marks source failures before metadata as
  incomplete, and keeps latest-available unresolved failures incomplete with no
  concrete requested dates.
- Added regression coverage for source failure before metadata,
  latest-available source failure, and range expanded requested/covered dates
  at the pipeline layer.

Post-repair verification:

- `pytest`: 174 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Fresh U2-B re-audit:

- Auditor `01a00f9a-2298-7322-871f-ce433e051611` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- The auditor confirmed the prior repair and broader U2-B coverage: pipeline
  propagation, schema v5 migration, legacy defaults, immutable snapshots,
  History/status/export metadata, cache reuse, partial retrieval,
  failure/retry, profile semantic invalidation, and run locking.

U2-B freeze:

- qualified commit: `b258c9be0ba1bfe67a9b5fac1ddad96429ac64a1`.
- qualified tag: `u2b-qualified`.
- qualified tag object: `1c7ab3dbf0ef187a6214c5106034731294abd058`.

## U2-C Candidate

Implementation summary:

- Replaced the Today workflow caption centered on lookback/max-results with
  UTC source-date wording.
- Added Today date-selection modes: latest available, single date, date range,
  and selected dates.
- Added visible digest-period labels before starting a run and after a run
  completes.
- Today manual runs now call the shared service with `DateSelection` and
  `RunOrigin.MANUAL`.
- Added incomplete retrieval warning support for safety-capped/partial date
  retrievals.
- Updated Today state tests so date selection, not legacy lookback/max-results,
  drives normal run signatures.

Candidate deterministic verification:

- `pytest`: 178 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live UI smoke:

- `python -m research_digest.cli serve --port 18611`: failed with local socket
  `[Errno 1] Operation not permitted`.
- Same command after escalation: same result.

Audit status: fresh independent U2-C Auditor pending.

Initial independent U2-C Auditor:

- Auditor `01a00f9f-f81e-72f3-b9d6-13b5a4389290` returned FAIL with two
  IMPORTANT findings.
- Finding: latest-available mode did not show the concrete source date before
  starting a run.
- Finding: incomplete Streamlit date-range input state could raise during
  normal UI interaction.
- MINOR/OPTIONAL: the Sources page still exposes legacy `Lookback hours` and
  `Max results`; defer ordinary-user demotion/removal to U2-G unless a later
  substage requires earlier cleanup.

Repair round 1:

- Added a source-level `LatestAvailableDateResolver` protocol.
- Added `ArxivSource.resolve_latest_available_date()` using the same official
  arXiv API sort/source-date semantics as date-native retrieval.
- Today resolves latest available to a concrete single-date selection before
  enabling Run digest and displays that resolved date in the digest period.
- Incomplete date ranges now produce a pending state with a disabled Run digest
  button instead of a render exception.
- Date formatting no longer depends on GNU-only `strftime` day flags.

Post-repair verification:

- `pytest`: 184 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Fresh U2-C re-audit:

- Auditor `01a00fa5-7be2-7203-a7cf-ec19a8981f2c` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- The auditor confirmed date modes, exact pre-run date visibility for latest
  available, source-level latest-date resolution, pending/disabled incomplete
  range behavior, shared service use with `DateSelection` and
  `RunOrigin.MANUAL`, result period/incomplete warnings, and preservation of
  existing result/feedback controls.

U2-C freeze:

- qualified commit: `24230f3abeefb3cacf97c890247fca4f83e23388`.
- qualified tag: `u2c-qualified`.
- qualified tag object: `db857fc566645b477f2c928dd683f66430fbd2d8`.

## U2-D Candidate

Implementation summary:

- Added source-date coverage planning and persistence for automatic runs.
- Added schema version 6 with additive `source_date_coverage` scoped by
  profile semantic fingerprint and source semantic fingerprint.
- Added config version 3 with catch-up enabled by default and a conservative
  automatic coverage start date initialized at config creation/upgrade time.
- Changed headless `research-digest run` to use date-native uncovered-date
  catch-up with `RunOrigin.SCHEDULED`, rather than legacy rolling lookback.
- Coverage is only marked after complete retrieval and usable terminal digest
  semantics; failed, partial, and analyzer-unavailable-with-articles runs remain
  uncovered for retry.
- No-submission automatic runs can complete and be covered without an analyzer;
  analyzer unavailability still fails the command when retrieved articles
  actually need analysis.
- Empty/no-submission source dates can be covered after successful retrieval.
- CLI status exposes automation catch-up state, coverage anchor, and coverage
  count; JSON backup export preserves source-date coverage.

Migration/upgrade semantics:

- Legacy v0.1.0 rolling-lookback runs are not reinterpreted as source-date
  coverage because their exact source-date meaning cannot be established
  safely under the new contract.
- First upgrade/first schedule install does not backfill the full arXiv
  history; the default anchor is the UTC source date when config version 3 is
  created.

Candidate deterministic verification:

- `pytest`: 194 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live smoke:

- Disposable automatic arXiv headless smoke failed with DNS resolution failure
  for `export.arxiv.org`.
- Same smoke after network escalation failed with the same DNS result.

Initial independent U2-D Auditor:

- Auditor `01a00fb0-e605-7483-9d4a-3cff061a82e4` returned FAIL with one
  BLOCKER.
- Finding: U2-C config version 2 could not migrate to U2-D config version 3
  because the upgrade function only accepted versions 0 and 1.
- The auditor otherwise found U2-D coverage semantics consistent.

Repair round 1:

- Config migration now accepts version 2.
- Added a regression for upgrading a version-2 config with an existing
  `default_date_selection`, preserving it while adding automatic catch-up
  fields.

Post-repair verification:

- `pytest`: 195 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Fresh U2-D re-audit:

- Auditor `01a00fb5-4b7e-7b20-8360-656d5b3c003a` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- The auditor verified the config v2-to-v3 repair, additive schema migration,
  semantic coverage scope, catch-up planning, latest-only behavior when
  catch-up is disabled, date-native headless path, conservative terminal
  coverage rule, no-submission/analyzer behavior, and status/export visibility.

U2-D freeze:

- qualified commit: `4f98ef637891141f1716d5c017e3e1be4fba3d32`.
- qualified tag: `u2d-qualified`.
- qualified tag object: `d0866476699fde8067102ea4d9d9643b6cb3d422`.

## U2-E Candidate

Implementation summary:

- Added a shared automation service for schedule status, install/update,
  remove, and Run Now automatic execution.
- Settings now has an Automation section for automatic daily digest on/off,
  daily time, catch-up toggle, installed/health status, next run, last scheduled
  run, last scheduled digest outcome, timezone wording, Save / update schedule,
  Run now, and Disable schedule.
- Settings calls the same scheduler backend/request builder as CLI schedule
  commands; it does not construct Windows Task Scheduler commands.
- Run Now uses the same automatic catch-up/date-selection service as scheduled
  execution.
- Unsupported scheduler environments surface sanitized warnings while keeping
  Settings usable.
- Catch-up behavior is persisted through config helpers rather than direct JSON
  mutation.

Candidate deterministic verification:

- `pytest`: 202 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live smoke:

- Streamlit serve smoke failed with local socket `[Errno 1] Operation not
  permitted` before and after escalation.
- Windows Task Scheduler status smoke failed with WSL `UtilBindVsockAnyPort`
  socket failure before and after escalation.
- No schedule was installed or modified in this environment.

Fresh U2-E audit:

- Auditor `01a00fbe-173c-77c3-9a90-61612617af44` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- The auditor verified the Settings automation controls/status surfaces,
  shared automation/scheduler delegation, CLI routing through the same service,
  catch-up persistence, and sanitized unsupported-environment handling.

U2-E freeze:

- qualified commit: `536859eb87034dc55740f3b96b2d78d579d79622`.
- qualified tag: `u2e-qualified`.
- qualified tag object: `0dc19ab9b7b0937c32a0fd7feaf2afe0f20e8f57`.

## U2-F Candidate

Implementation summary:

- History labels now lead with source date/date set, origin, preselected count,
  and relevant count instead of primarily exposing run ids.
- Manual, Scheduled, and Legacy origins are visibly distinguished.
- Entry details show requested source dates, covered source dates,
  no-submission dates, incomplete retrieval warnings, and the required
  retrieved/preselected/analyzed/relevant counts.
- Status labels use user-facing wording including No submissions.
- Immutable run snapshots and historical run ids are preserved; legacy runs are
  not reinterpreted.
- No Library, tagging, memory, notes, collections, search, or run merging was
  introduced.

Candidate deterministic verification:

- `pytest`: 204 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Fresh U2-F audit:

- Auditor `01a00fc5-60d9-7411-b955-61b651dfb890` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- The auditor verified date/date-set-led History labels, requested/covered
  source dates, origin labels, completion/failure/partial detail surfaces,
  retrieved/preselected/analyzed/relevant counts, persisted synthesis, run
  times, separate historical runs, immutable snapshot semantics, and no M6
  Library/tagging/memory additions.
- Auditor checks: focused History pytest passed; focused History plus pipeline
  pytest passed; `git diff --check` PASS.
- OPTIONAL: future polish could show Partial directly in the selectbox/status
  label and format requested/covered detail captions as friendly dates.

U2-F freeze:

- qualified commit: `4ec80f759c4db041759b9dab550e390559afaa9b`.
- qualified tag: `u2f-qualified`.
- qualified tag object: `f63a39f33060b980889214e918b395d081de1f00`.

## U2-G Candidate

Implementation summary:

- Settings now presents General, Analysis, Automation, Data, and Health
  sections for normal administration.
- General shows the app version, schema/config versions, active SQLite data
  path, configuration path, data directory, and configuration directory.
- Analysis shows the configured analyzer provider, non-secret model/runtime
  details, provider health from the existing doctor/provider check, and the M2
  preselection effort model.
- Automation preserves the U2-E shared scheduler UI/service behavior.
- Data adds Backup now through the existing backup service, including the
  already-qualified optional JSON export sidecar and sanitized failure display.
- Health continues to render the existing doctor report and checks through
  `run_doctor()`.
- The normal Sources form no longer presents `lookback_hours` or `max_results`;
  saving arXiv enabled/categories preserves legacy stored values for
  administrative compatibility.
- The previous primary Release commands Settings block was removed from the
  ordinary Settings surface.

Candidate deterministic verification:

- focused Settings/Sources tests: 11 passed.
- `pytest`: 210 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Live smoke:

- `python -m research_digest.cli serve --port 18612` failed with local socket
  `[Errno 1] Operation not permitted`.
- Same command after escalation failed with the same result.

Fresh U2-G audit:

- Auditor `01a00fcd-4dcb-7ce2-aaeb-772be6644c8c` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- The auditor verified Settings section coverage, shared doctor/automation/
  backup service boundaries, no secret exposure, normal Sources removal of
  `lookback_hours`/`max_results`, legacy limit preservation, and no scope
  expansion.
- Auditor checks: full pytest passed, focused Settings/Sources pytest passed,
  `ruff check .` PASS, strict mypy PASS, compileall over touched files PASS,
  and `git diff --check u2f-qualified` PASS.
- OPTIONAL: Settings backup directory display hardcodes the current backup
  directory name instead of importing `backup.DEFAULT_BACKUP_DIRNAME`; behavior
  matches the backup service.

U2-G freeze:

- qualified commit: `908a4d3a673b65a18c66d5c03ee70bb267f4f3d1`.
- qualified tag: `u2g-qualified`.
- qualified tag object: `8dac248a8956d64cd51074be38cd2f237742c6b8`.

## U2-H Candidate

Implementation and documentation summary:

- Bumped package/runtime version to `0.2.0`.
- Updated README for date-native manual digests, arXiv UTC source-date
  semantics, UI-managed daily automation, catch-up coverage semantics,
  Settings backup/data/health, v0.1.0 upgrade expectations, and unchanged
  release limitations.
- Added `docs/campaigns/v0.2/RELEASE_CANDIDATE_PACKET.md` with release notes,
  upgrade notes, date-selection guide, scheduler UI guide, schema/config
  changes, backup/recovery instructions, known limitations, deferred optional
  findings, and human-only release command sketch.
- Added deterministic v0.1.0-style schema/config upgrade coverage preserving
  history snapshots, legacy source settings, semantic data, and config backup
  behavior.
- Updated package/wheel and installed CLI version expectations to `0.2.0`.

Actual v0.1.0 disposable upgrade smoke:

- Created a disposable checkout of exact tag `v0.1.0` at commit
  `905f3133b58b6248fe4d3714c19f8bcdf9dde4cf`.
- Used released v0.1.0 code with isolated `/tmp` data/config paths and a
  synthetic profile/article/analysis/feedback/run to create schema 4/config 1.
- Reopened the same disposable data/config with current v0.2 candidate code.
- Verified schema 6, config 3, preserved one synthetic profile, article,
  analysis, feedback, and app run; run origin `LEGACY`; requested dates empty;
  preserved legacy arXiv `lookback_hours=72` and `max_results=25`; conservative
  coverage start date; zero coverage rows; backup/export success.

Candidate deterministic verification:

- focused release matrix/docs tests: 8 passed.
- initial `pytest`: 211 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- migration inventory: version `0.2.0`, config version 3, schema version 6,
  migrations 1 through 6.
- package build: `python -m pip wheel . --no-deps` produced
  `research_digest-0.2.0-py3-none-any.whl`.
- isolated wheel install: PASS.
- installed CLI smokes: `research-digest --version` reported `0.2.0`;
  `status --json` initialized schema 6/config 3 in disposable paths;
  `doctor --json` ran from the installed wheel and returned no failures with
  expected fresh-environment warnings.

Live smoke:

- live arXiv latest-available smoke failed with DNS resolution failure for
  `export.arxiv.org` before and after network escalation.
- Streamlit serve smoke failed with local socket `[Errno 1] Operation not
  permitted` before and after escalation.
- Windows Task Scheduler status smoke failed with WSL
  `UtilBindVsockAnyPort` socket failure before and after escalation.

Audit status: fresh independent U2-H Auditor pending.

Fresh U2-H audit:

- Auditor `01a00fd9-92c0-7420-88c7-90ead1a806d7` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- Auditor verified the `u2g-qualified` and `v0.1.0` baselines, version/config/
  schema inventory, focused U2-H release/docs checks, a broad compatibility
  surface, and diff hygiene.
- Auditor MINOR/OPTIONAL findings: campaign state `current_git_head` was stale;
  arXiv user agent still used `ResearchDigest/0.1`.

Minor repair:

- Corrected campaign state `current_git_head` to the literal pre-candidate
  branch HEAD `211c64ee2dbdbfc58d73fa819b673b4843a4b69e`.
- Changed the default arXiv user agent to derive from package `__version__`.
- Added a regression that the default arXiv user agent tracks the package
  version.
- Post-repair verification: `pytest` 212 passed; `ruff check .` PASS;
  strict mypy PASS; compileall PASS; `git diff --check` PASS.
- Rebuilt wheel from current source:
  `research_digest-0.2.0-py3-none-any.whl`.
- Re-ran isolated installed wheel smoke:
  `research-digest --version` reported `0.2.0`; `status --json` initialized
  schema 6/config 3 in disposable paths.

Focused U2-H post-repair audit:

- Auditor `01a00fde-b7e3-7fd3-bc16-2271e538bebf` returned PASS.
- No BLOCKER, IMPORTANT, MINOR, or OPTIONAL findings were newly identified.
- Auditor verified no circular import risk from the version-derived arXiv user
  agent, package/runtime version consistency, corrected campaign state HEAD,
  RC packet consistency, focused tests, import smoke, ruff, and diff hygiene.

U2-H freeze:

- qualified commit: `37cc990dd5e793a2ac84d9d2591b34037638ec9c`.
- qualified tag: `u2h-qualified`.
- qualified tag object: `8f13e93661ac80c43c9b996bbcff859f303bbce0`.

## Final RC Gate

Status: final independent RC audit over the complete delta from `v0.1.0`
pending.
