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

## Integrated RC Live-Smoke Repair

Status: PASS after closure audits, later category-order source identity repair,
and accepted human live smoke.

Human live smoke found four concrete defects in the date coverage and Run Now
UI:

- A completed manual single-date digest for 2026-08-14 was still rendered as
  pending/uncovered in the Today calendar.
- Automation had `Catch up from` later than latest available and correctly
  showed no pending source dates in text, but the month calendar rendered many
  dates as pending.
- Run Now with zero pending dates produced no visible response.
- Long calendar status strings wrapped inside narrow day cells.

Repair summary:

- Moved successful date-native coverage marking into the shared
  `run_digest_for_profile` service path after snapshot persistence, so manual
  Today runs, Automation Run Now, and scheduled execution feed the same durable
  `source_date_coverage` semantics.
- Kept failed, partial, and analysis-unavailable runs retry-eligible; later
  completed coverage supersedes earlier failed/partial attempts for current
  calendar/coverage presentation while History remains immutable.
- Made the date-status builder default dates to `out_of_scope` and mark
  `pending` only from the explicit catch-up plan pending-date set.
- Preserved profile/source semantic fingerprint isolation for completed,
  failed, partial, empty, pending, and neutral states.
- Changed Automation Run Now to compute pending dates before acquiring the
  analyzer or starting work. A zero-pending Run Now now shows an informational
  no-op message and creates no app run/history row.
- Kept pending Run Now on the shared automation/headless service path and
  reruns Streamlit after completion so coverage and History refresh without
  duplicate execution.
- Replaced long in-cell calendar labels with compact non-color-only markers and
  a legend/details table for full labels, selected overlay, run id, and counts.
- Added a Today rerun after successful manual digest completion so the calendar
  refreshes from durable coverage immediately.

Regression coverage added:

- Manual completed date marks durable coverage, appears completed, is no longer
  pending, and is not redundantly scheduled.
- Manual analysis-unavailable/partial date remains pending; successful retry
  later marks completed while the earlier historical attempt remains.
- Calendar statuses no longer default an entire visible month to pending.
- Source/category fingerprint changes do not leak completed status across
  source semantics.
- Run Now zero-pending wrapper creates no history run; pending Run Now invokes
  the shared digest service and persists coverage.
- Run Now no-op message explains the catch-up anchor and latest available date.
- Compact calendar cell labels avoid long strings such as `Pending/uncovered`
  while details retain the full status text.

Verification:

- Initial live-smoke repair `pytest`: 243 passed.
- Fresh closure auditor `01a010fb-0cfe-7133-97f7-8655b59e82dd` found three
  IMPORTANT gaps: aggregate pending dates caused already-covered profiles to
  be rerun when another profile was pending; non-`COMPLETED`
  analysis-unavailable runs could mark coverage if analyses were cached; Run
  Now completion feedback lacked run ids and date outcome counts.
- Repair round 1 made automatic execution recompute pending dates per profile
  while retaining the aggregate pending display, required
  `DigestResult.run_status == COMPLETED` before marking durable coverage, and
  expanded Run Now summaries with run ids plus completed/empty/partial/failed
  date outcomes. It also aligned headless profile success with the same
  `COMPLETED` terminal state.
- Repair round 1 regressions cover per-profile catch-up isolation,
  analysis-unavailable cached-analysis runs staying retry-eligible, and Run
  Now run-id/outcome summary content.
- Repair round 1 `pytest`: 247 passed.
- Fresh re-auditor `01a01102-c911-7b73-801c-07eb0bb1efa5` found two
  IMPORTANT gaps: failed/partial/empty app-run status overlays were not scoped
  by profile semantic fingerprint, and headless success reporting did not
  require the same retrieval-complete/no-incomplete-date coverage eligibility
  used by durable coverage.
- Repair round 2 adds additive nullable `app_runs.profile_fingerprint`, stores
  the current profile semantic fingerprint on new app runs, filters calendar
  app-run overlays by it, shares `digest_is_coverage_eligible()` between
  coverage marking and date-native headless success, and reports retrieval
  incomplete source dates as profile errors.
- Fresh re-auditor `01a01109-519e-7313-83bd-fc4c8f145d46` found one remaining
  IMPORTANT detail issue: completed calendar status eligibility was scoped, but
  the run id/count detail lookup did not filter `source_date_coverage` by
  profile semantic fingerprint.
- Detail repair passes the profile fingerprint into completed coverage detail
  lookup and adds a regression for profile semantic A covered, semantic B
  covered later, then semantic A current calendar displaying semantic A's run
  id and counts.
- Detail repair `pytest`: 249 passed.
- Fresh re-auditor `01a0110d-4f1d-7680-af5b-3fa9a2a808db` found one remaining
  IMPORTANT UI reporting gap: Run Now date outcomes still counted
  `COMPLETED` app-run status as completed even when retrieval was incomplete
  and the digest was not coverage-eligible.
- Final UI summary repair makes Run Now completed-date counting use
  `digest_is_coverage_eligible()` and reports incomplete/truncated completed
  statuses as partial/incomplete. Regression coverage asserts the visible
  summary reports completed 0, partial 1 for this case.
- Final UI summary repair `pytest`: 250 passed.
- Fresh re-auditor `01a01111-88ee-72b1-ace8-4a43f213b5a1` found one remaining
  IMPORTANT Run Now reporting gap: result notices were always stored as
  success after the headless service returned, and summaries did not include
  sanitized profile failure details.
- Final Run Now failure-reporting repair chooses notice level from the result
  (`error` when all attempted profiles fail, `warning` for mixed outcomes,
  `success` only with no failed profiles) and includes sanitized per-profile
  error messages in the visible summary.
- Final Run Now failure-reporting repair `pytest`: 251 passed.
- Fresh closure auditor `01a01115-c3f5-7041-92b6-cc9c16b7d169` returned PASS
  with no BLOCKER or IMPORTANT findings. It verified durable manual coverage,
  profile-scoped automatic catch-up, profile/source scoped calendar overlays
  and completed details, coverage-eligible headless success, truthful Run Now
  no-op/execution summaries, compact calendars, and preservation of prior RC
  repairs.
- The prior MINOR/OPTIONAL category-order source fingerprint caveat was later
  promoted by human live smoke and resolved in the category-order source
  identity repair below.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

## Category-Order Source Identity Repair

Status: PASS after repair round 1, fresh focused closure re-audit, and final
human live smoke.

Follow-up human live smoke found one remaining correctness defect: completed
dates for source categories `hep-th` and `gr-qc` became pending/uncovered after
only reversing the category order to `gr-qc` and `hep-th`.

Repair summary:

- Added one canonical arXiv category representation at the domain boundary:
  trim/collapse whitespace, drop blanks, deduplicate, and sort into a stable
  tuple.
- `ArxivSourceConfig` now stores categories in canonical order, so UI save and
  config reload preserve semantic equality for equivalent category sets.
- Source semantic fingerprints, Today digest input signatures, coverage scope,
  pending-date calculation, automatic catch-up, and source-scoped app-run
  calendar overlays use the canonical category set.
- Existing v0.2 RC coverage/app-run rows written with the earlier
  order-sensitive fingerprint are not orphaned: coverage reads accept the
  canonical fingerprint and compatible legacy fingerprints for permutations of
  the same canonical category set.
- Actually changing the category set still creates a distinct source scope.

Regression coverage added:

- `hep-th, gr-qc`, `gr-qc, hep-th`, duplicate entries, and whitespace variants
  produce the same source fingerprint and Today digest input signature.
- Reordering categories after successful manual coverage keeps Today and
  Automation calendars completed, preserves the pending-date set, and prevents
  redundant scheduled execution.
- Pre-repair order-sensitive persisted coverage remains visible after category
  reorder.
- Reordering categories does not invalidate otherwise valid cached analysis.
- Replacing a category with a different category creates a new source scope.
- Config serialization/reload preserves semantic equality.

Focused verification:

- `pytest tests/test_models.py tests/test_today_state.py tests/test_sources_page.py tests/test_arxiv.py tests/test_coverage.py tests/test_db.py`:
  97 passed.
- Candidate full deterministic gate:
  - `pytest`: 260 passed.
  - `ruff check src tests`: PASS.
  - `mypy --strict src tests`: PASS.
  - `python -m compileall src tests`: PASS.
  - `git diff --check`: PASS.
- Fresh focused Auditor `01a01139-b7a8-7c60-938a-468a59702a7c` returned FAIL
  with two IMPORTANT findings: duplicate-category legacy fingerprints were not
  reconciled, and completed `app_runs` metadata was not used as a completed
  fallback when a durable `source_date_coverage` row was absent.
- Repair round 1 added bounded legacy alias recognition for old fingerprints
  generated from sequences containing only the same canonical category set,
  including duplicate category entries, and added completed app-run covered-date
  fallback for planning/calendar status when a coverage row is missing.
- Repair round 1 added regressions for duplicate pre-repair coverage
  fingerprints, scheduler no-op after duplicate-fingerprint reorder, and
  completed app-run-only fallback retaining run details without creating a
  coverage row.
- Repair round 1 full deterministic gate:
  - `pytest`: 262 passed.
  - `ruff check src tests`: PASS.
  - `mypy --strict src tests`: PASS.
  - `python -m compileall src tests`: PASS.
  - `git diff --check`: PASS.
- Fresh focused closure re-auditor `01a0113f-400e-7202-9455-c9ba95f7042d`
  returned PASS with no BLOCKER, IMPORTANT, MINOR, or OPTIONAL findings. The
  auditor verified canonical source identity, bounded duplicate legacy alias
  recognition, completed app-run fallback requirements, Today/Automation shared
  calendar status, cache reuse under reorder, and preservation of prior RC
  repairs.
- Re-auditor read-only verification:
  - focused repair/regression tests: 157 passed.
  - full `pytest`: 262 passed.
  - `ruff check .`: PASS.
  - `mypy --cache-dir /tmp/research-digest-mypy-cache src tests`: PASS.
- Final human live smoke verified that `hep-th`/`gr-qc` shows Aug 12, Aug 13,
  and Aug 14 completed; reordering only to `gr-qc`/`hep-th` preserves completed
  coverage, pending-date state, source scope, and existing analysis/cache state;
  no new History run is created and no analysis rerun occurs. Actually changing
  the category set creates a distinct source scope as intended.
- All previous integrated human-smoke items were also accepted: America/Chicago
  source-date semantics, robust chunked Codex analysis/retry, durable manual
  coverage, successful retry superseding old failed calendar state, Catch up
  from semantics, Run Now execution/no-op feedback, compact scoped coverage
  calendar, no-submission state, abstract toggles, and History behavior.

## Final RC Freeze

Status: final deterministic qualification PASS against the accepted integrated
RC repair tree before the authorized local RC commit. No public `v0.2.0` tag,
remote push, package publication, or public release is authorized by this
state.

Planned local-only freeze actions:

- Run the final deterministic qualification gate: PASS.
- Stage and inspect the complete RC repair inventory for secrets/runtime state.
- Commit locally.
- Create or update the local qualification tag `v0.2-rc-qualified`.
- Stop for final human release decision.

Final deterministic freeze gate:

- `pytest`: 262 passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

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

Historical source-date note: U2-A originally qualified UTC Atom `published`
date semantics. The later integrated RC repair supersedes that decision with
arXiv public listing/mail dates reconstructed from official `submittedDate`
windows. That listing-date repair was later superseded by human authority:
current behavior and release notes use America/Chicago publication-date
conversion.

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
- Updated README for date-native manual digests, arXiv source-date semantics,
  UI-managed daily automation, catch-up coverage semantics,
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

Initial final RC audit:

- Auditor `01a00fe1-236a-7cb1-9f52-23dd744bb84c` returned FAIL with two
  IMPORTANT bookkeeping findings.
- Finding 1: the RC packet still said the release-candidate commit was pending.
- Finding 2: campaign state recorded a stale current HEAD.
- Auditor checks otherwise passed: full pytest, targeted RC tests, ruff,
  strict mypy, diff hygiene, clean worktree, no local `v0.2*` tag, and no
  tracked secrets/auth/SQLite artifacts.
- Repair round 1: RC packet now identifies the stable qualified release code
  commit `37cc990dd5e793a2ac84d9d2591b34037638ec9c` and explicitly notes that
  later campaign bookkeeping commits only update campaign state/report/packet
  records. Campaign state no longer tries to embed the SHA of the commit that
  contains the state file; use `git rev-parse HEAD` for that literal value.

Status: superseded by integrated RC repair and final category-order source
identity repair.

Focused final RC re-audit:

- Auditor `01a00fe7-9c25-7123-86f8-1ad33d29a35d` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- Worktree was clean at audit time, no local `v0.2*` tag existed, and the RC
  packet/state clearly distinguish qualified release code commit
  `37cc990dd5e793a2ac84d9d2591b34037638ec9c` from later campaign-only
  bookkeeping commits.
- No new MINOR/OPTIONAL findings were identified.

Final state:

- `CAMPAIGN_STATE` set to
  `V0_2_RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN`.
- No public `v0.2.0` tag, remote push, package publication, or GitHub release
  was created automatically.

## Integrated RC Repair Reopened

Status: in progress.

Scope:

- Robust chunked full-analysis batching with bounded retry/fallback.
- arXiv source dates changed from UTC Atom `published` calendar dates to arXiv
  public listing/mail dates reconstructed from official `submittedDate`
  windows.
- Settings Automation exposes editable `Catch up from` and pending-date status.
- Today/Automation expose scoped date-status grids with completed, failed,
  partial/incomplete, no-submission, pending, and selected labels.
- Abstract display repair preserved; real browser smoke remains blocked by this
  environment's local socket restriction and is carried to human live smoke.

Implementation notes:

- SQLite schema 7 adds nullable `app_runs.source_fingerprint` so failed/partial
  statuses are not shown across changed source-category semantics. Closure
  repair schema 8 adds nullable `app_runs.profile_fingerprint` so
  failed/partial/empty statuses are not shown across changed profile semantics.
- Partial analysis runs persist valid successful analyses promptly, do not
  re-request validated papers in fallback phases, and leave unresolved papers
  retryable on the next date run.
- Headless profile aggregate success now requires complete analysis; partial
  and analysis-unavailable runs remain persisted for retry and are surfaced as
  incomplete/failure-like outcomes in summaries.

Integrated deterministic verification:

- `pytest`: 228 passed, 9 subtests passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Live smoke status:

- Real serve/browser smoke remains blocked by sandbox socket binding
  restrictions and is not treated as a code failure.
- Human live-smoke checklist created:
  `docs/campaigns/v0.2/RC_REPAIR_LIVE_SMOKE_CHECKLIST.md`.

Initial integrated RC-repair audit:

- Auditor `01a01072-57e8-71d1-b954-058cd37b9f48` returned FAIL with two
  IMPORTANT findings.
- Finding 1: date-status grids could show stale failed/partial/empty state
  after a later successful retry because older app-run status artifacts could
  override completed scoped coverage.
- Finding 2: arXiv source-date semantics lacked a deterministic known-listing
  fixture with an expected article-ID set.

Repair round 1:

- Completed scoped digest coverage now dominates older failed/partial/empty
  app-run artifacts in date-status grids.
- Added a regression proving an older partial run cannot keep a date partial
  after a later successful digest marks the scoped source date covered.
- Added a minimal deterministic arXiv public-listing fixture for the
  `2025-01-07` listing window with expected article IDs `2501.02703` and
  `2501.02704`, duplicate category-overlap handling, and update-only exclusion.
- Direct official arXiv API capture for `2026-08-14` `hep-th` + `gr-qc` was
  attempted with `curl` before and after network escalation; both attempts
  failed with DNS resolution failure for `export.arxiv.org`.

Repair round 1 deterministic verification:

- `pytest`: 230 passed, 9 subtests passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Integrated RC-repair re-audit:

- Auditor `01a01079-4703-71b1-898c-69a5370ec6bf` returned FAIL with three
  IMPORTANT findings.
- Finding 1: real no-submission dates were displayed as `Completed digest`
  instead of `Checked: no submissions` because completed coverage masked the
  empty app-run status.
- Finding 2: the added deterministic listing fixture was not a captured
  complete official daily listing; it was a minimal hand-curated feed from
  individual abstract-page evidence.
- Finding 3: Today could hide preselected-out cards when a run had no analyzed
  items, preventing required preselected-out abstract controls in that edge
  case.

Repair round 2:

- Date-status merging now preserves `Checked: no submissions` for covered
  empty dates while still letting completed non-empty coverage dominate older
  failed/partial artifacts.
- Added service-path coverage regression for scheduled no-submission dates.
- Today no longer returns before rendering preselected-out and unresolved
  sections when the selected analyzed-item view is empty.
- Added Streamlit AppTest coverage for an all-preselected-out Today result and
  its abstract toggle.

Repair round 2 deterministic verification:

- `pytest`: 231 passed, 9 subtests passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Human stop:

- RC repair is blocked on arXiv source-date authority. Official arXiv
  availability documentation states announcement windows in Eastern US time.
  The official API manual states `submittedDate` query timestamps are in GMT.
  An arXiv API Discussion answer from arXiv staff gives a mailing
  reconstruction example using a 14:00 `submittedDate` boundary, not the 19:00
  GMT value implied by converting a 14:00 Eastern cutoff during EST.
- That ambiguity materially changes which submissions belong to a source date.
- The sandbox cannot reach `export.arxiv.org` to capture a complete official
  API listing fixture for the desired regression case; `curl` attempts before
  and after network escalation failed with DNS resolution failure.
- Campaign state is set to
  `V0_2_RC_REPAIR_BLOCKED_AWAITING_HUMAN_SOURCE_DATE_AUTHORITY`.

## Integrated RC Repair Resumed

Human authority decision:

- Research Digest does not attempt to reconstruct or duplicate arXiv mailing,
  announcement-day, or daily-listing cutoff semantics.
- v0.2 arXiv source dates use America/Chicago calendar dates obtained by
  converting each article's authoritative arXiv publication timestamp to the
  IANA timezone `America/Chicago`.
- Timezone-aware conversion is required; CST/CDT transitions follow timezone
  database rules.
- The same source-date definition must be used by single date, date range,
  selected dates, latest available, scheduler catch-up, `Catch up from`,
  coverage state/calendar, History, and run snapshots.
- API `submittedDate` ranges may be used only to retrieve a safe superset of
  candidates; final date membership is local
  `published timestamp -> America/Chicago -> source_date` filtering.
- UI/docs must not call this an arXiv announcement, mailing, or listing date.

Implementation after human authority:

- Replaced arXiv listing-window source-date helper with America/Chicago
  publication-time conversion.
- Replaced listing-window API date ranges with padded UTC candidate windows
  around Chicago-local source-date boundaries.
- Updated Today UI source-date caption to `Source dates use America/Chicago.`
- Updated durable source-date semantics documentation, README, RC packet, and
  live-smoke checklist.
- Removed the supplemental listing fixture so it cannot be mistaken for an
  authoritative requirement.

Focused verification:

- `pytest tests/test_arxiv.py tests/test_models.py tests/test_pipeline.py
  tests/test_coverage.py tests/test_today_state.py tests/test_settings_page.py
  tests/test_history.py tests/test_abstract_ui_smoke.py`: 108 passed, 3
  subtests passed.
- Focused `ruff check`: PASS.
- Focused `mypy --strict`: PASS.

Deterministic qualification after America/Chicago repair:

- `pytest`: 234 passed, 9 subtests passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Fresh integrated America/Chicago audit:

- Auditor `01a010c1-c09f-7d02-8767-63c605166703` returned FAIL with two
  IMPORTANT findings.
- Finding 1: empty/no-submission dates could display as `Completed digest`
  instead of `Checked: no submissions` when no analyzer was configured because
  the pipeline marked analyzer-absent empty runs as `ANALYSIS_UNAVAILABLE`.
- Finding 2: this campaign report's earlier U2-A note still described the
  abandoned listing/mail-date repair as current behavior.

Repair after audit:

- Analyzer-absent runs with `retrieved_count == 0` now remain completed and
  analysis-available because no analysis is needed.
- Added a scheduled no-submission/no-analyzer regression that verifies
  completed run status, no analysis-unavailable aggregate, and `Checked: no
  submissions` calendar display.
- Corrected the stale campaign-report source-date note to state that
  America/Chicago publication-date conversion is current behavior.

Focused verification:

- `pytest tests/test_coverage.py tests/test_pipeline.py
  tests/test_run_lifecycle.py`: 42 passed, 3 subtests passed.
- Focused `ruff check`: PASS.
- Focused `mypy --strict`: PASS.

Full deterministic requalification after audit repair:

- `pytest`: 235 passed, 9 subtests passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Fresh integrated re-audit:

- Auditor `01a010c6-2969-76b0-bb49-6f5e715ffe47` returned PASS.
- No BLOCKER or IMPORTANT findings remain.
- Auditor MINOR: source-date conversion existed in both `models.py` and
  `arxiv.py`, creating drift risk against the documented shared helper.

Minor repair:

- `arxiv_source_date_from_datetime()` now delegates to
  `models.source_date_from_datetime()`.
- arXiv query-window construction now uses the shared source-date timezone
  object from `models.py`.
- Focused verification after minor repair:
  `pytest tests/test_arxiv.py tests/test_models.py tests/test_coverage.py`:
  46 passed; focused mypy PASS.

Final deterministic verification after minor repair:

- `pytest`: 235 passed, 9 subtests passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Superseded repair state before later integrated RC live-smoke repairs:

- Integrated RC repair is qualified for the planned human live smoke.
- Campaign state is set to
  `V0_2_RC_REPAIR_QUALIFIED_AWAITING_HUMAN_LIVE_SMOKE`.
- No commit, tag, push, package publication, or public release was created.
