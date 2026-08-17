# v0.2 Campaign State

- campaign_state: U2_B_QUALIFIED_FROZEN
- current_substage: U2-C Today date-selection UI
- current_git_head: b258c9be0ba1bfe67a9b5fac1ddad96429ac64a1
- current_branch: feature/v0.2-date-native-scheduler-ui
- released_baseline_tag: v0.1.0
- released_baseline_commit: 905f3133b58b6248fe4d3714c19f8bcdf9dde4cf
- released_baseline_tag_object: be5925e7172ab788dde674669fd7d82068038b92
- current_master_origin_state: local master and local origin/master both resolve to 70fdd312439342defdb1d4036cc71802c001af9c
- online_remote_verification: attempted `git ls-remote --heads --tags origin`; blocked by DNS resolution failure for `github.com` before and after network escalation.
- package_version: 0.1.0
- runtime_version: 0.1.0
- schema_version: 5
- config_version: 2
- worktree_state_at_campaign_start: clean tracked worktree; ignored runtime files include `.env`, local SQLite, virtualenv, caches, and local agent/runtime directories.
- qualification_state: U2-B PASS after repair round 1 and fresh re-audit; U2-B frozen locally.
- audit_round: 1
- deterministic_checks: baseline `pytest` 149 passed; U2-A post-repair `pytest` 166 passed; U2-B post-repair `pytest` 174 passed; `ruff check .` PASS; `mypy --strict src tests` PASS; `python -m compileall -q src tests` PASS; `git diff --check` PASS. Fresh re-auditor independently ran equivalent deterministic checks with PASS.
- live_checks: U2-A live arXiv latest-available smoke attempted with bounded timeout; blocked by DNS resolution failure for `export.arxiv.org` before and after network escalation.
- schema_config_migration_state: v0.1.0 uses ordered SQLite migrations through schema version 4 and JSON config version 1; U2-A raises JSON config to version 2; U2-B candidate raises SQLite schema to version 5 with additive app-run date metadata defaults that preserve legacy historical run meaning.
- qualified_local_commit: b258c9be0ba1bfe67a9b5fac1ddad96429ac64a1
- qualified_local_tag: u2b-qualified
- qualified_local_tag_object: 1c7ab3dbf0ef187a6214c5106034731294abd058
- u2a_qualified_commit: 616d84209c7295de2884d4ae82df0a5bd222d397
- u2a_qualified_tag: u2a-qualified
- u2a_qualified_tag_object: 84e22c2eaa2b67c1dc6000fe4cc42e25a7f32e7c
- deferred_minor_optional_findings: U2-A re-auditor OPTIONAL: future hardening could add a separate raw API-row/page scan ceiling for malformed or inconsistent API responses; not required for U2-A after explicit-date repair.
- next_permitted_action: begin U2-C planning/implementation.
- human_stop_reason: none

## Recovered v0.1.0 Baseline

- `v0.1.0` is an annotated release tag targeting commit `905f3133b58b6248fe4d3714c19f8bcdf9dde4cf`.
- Current `HEAD` is commit `70fdd312439342defdb1d4036cc71802c001af9c`, one post-tag documentation/bookkeeping commit after `v0.1.0`.
- The delta from `v0.1.0..HEAD` is limited to release1 campaign documentation.
- `README.md`, `pyproject.toml`, and `src/research_digest/__init__.py` report version `0.1.0`.
- Current release1 scheduler behavior includes the repaired Codex PATH capture for WSL2/Windows Task Scheduler, no embedded API keys, no Codex auth paths, and doctor stale-PATH warnings.
- Existing data/config migration architecture:
  - SQLite schema migrations are ordered in `research_digest.db.MIGRATIONS`.
  - Existing schema-changing upgrades create a SQLite backup before migration.
  - JSON config is versioned in `research_digest.config` and rejects secrets or unknown keys.
  - Persistent user data/config live outside replaceable source code by default.

## Campaign Charter

This campaign targets the next feature release, provisionally v0.2.0. It must
stop before final public release, final public tag, package publication, or
remote push unless the human makes the final release decision.

Product goals:

- Manual digests support latest available source date, one explicit date,
  contiguous date range, multiple explicit dates, and all eligible source
  articles for those dates.
- Automatic digests use UI-managed daily scheduling, deterministic catch-up of
  missed source dates, and no normal rolling lookback dependency.
- Scheduler UI exposes enable, disable, edit daily time, timezone semantics,
  installed state, next run, last scheduled run, health/errors, Run Now, and
  catch-up configuration.
- History records requested/covered source dates, manual vs scheduled origin,
  and immutable historical run semantics.

Scope exclusions:

- M3 RSS, generic Atom feeds, journal APIs, arbitrary websites, HTML scraping,
  and additional source families.
- M5 PDF/full-paper reading and deep-paper analysis.
- M6 saved Library, user collections, AI/user tags, editable/removable tags,
  notes/projects, vector search, and long-term semantic memory.
- Redis, Celery, distributed services, authentication/multi-user systems,
  vector databases, generic plugin frameworks, or frontend frameworks replacing
  Streamlit.

Operational model:

- Use the persistent Worker for each substage implementation/repair.
- Use a fresh independent read-only Auditor after each candidate.
- Default audit repair budget is initial candidate plus two audit-driven repair
  rounds per substage.
- Ordinary pre-audit implementation/test repairs do not count against the audit
  repair budget.
- Do not weaken tests or acceptance criteria to obtain PASS.
- Commit locally and create local annotated qualification tags only after a
  substage is qualified.
- Suggested U2 qualification tags: `u2a-qualified`, `u2b-qualified`,
  `u2c-qualified`, `u2d-qualified`, `u2e-qualified`, `u2f-qualified`,
  `u2g-qualified`, and `u2h-qualified`.

Human stop conditions:

- Materially different interpretations would change product behavior.
- A repair requires changing this frozen product contract.
- A security or permission boundary must be weakened.
- New paid service, credentials, or external authorization are required.
- Repository/data integrity becomes ambiguous.
- Worker/Auditor evidence remains irreconcilable.
- Audit repair budget is exhausted.
- Final v0.2.0 release-candidate gate is reached.

Privacy and durability:

- Do not record personal interest descriptions, paper contents, SQLite
  contents, API keys, Codex auth material, or local auth paths in campaign docs.
- Preserve the v0.1.0 invariant: code is replaceable and user data survives
  independently.

## Frozen U2-A Plan

Goal: replace rolling-lookback semantics in the normal digest retrieval path
with explicit source-date selection for arXiv while preserving v0.1.0 data and
admin compatibility.

1. Add a typed date-selection domain.
   - Introduce `DateSelectionKind` and immutable `DateSelection`.
   - Supported modes: `LATEST_AVAILABLE`, `SINGLE_DATE`, `DATE_RANGE`, and
     `EXPLICIT_DATES`.
   - Normalize duplicate explicit dates, sort dates ascending, reject empty
     explicit selections, reject reversed ranges, and provide stable display and
     fingerprint helpers.
   - Store dates as Python `date` values, not UI-local datetimes.

2. Document arXiv source-date semantics.
   - For U2-A, use the official arXiv Atom API `published` timestamp as the
     source-native date because it is present in existing official API metadata
     and already maps to `Article.published_at`.
   - Define source date as the UTC calendar date of `atom:published`.
   - Retrieval, History metadata, scheduler catch-up, tests, and UI must use the
     same UTC source-date semantics.
   - Do not silently mix UI local dates with retrieval UTC dates. Future UI
     wording must say arXiv source dates are UTC.
   - Detailed decision note: `docs/campaigns/v0.2/ARXIV_SOURCE_DATE_SEMANTICS.md`.
   - If later evidence shows a materially different official daily-announcement
     date is available through the existing API and should control normal
     behavior, stop for human authority before switching semantics.

3. Extend source retrieval without breaking existing adapter compatibility.
   - Keep `SourceAdapter.fetch(config, now=...)` for legacy/admin callers.
   - Add a date-native arXiv retrieval method/service path that accepts
     `DateSelection`.
   - Implement pagination over the official arXiv API using `start` and
     `max_results`.
   - Fetch until selected dates are exhausted or no more matching entries are
     returned.
   - Deduplicate arXiv entries by stable arXiv id across categories/pages.
   - Preserve deterministic ordering by source date then timestamp/title/id.

4. Use an internal safety ceiling.
   - Add a conservative internal ceiling that is not exposed as a normal user
     max-results control.
   - If the ceiling is reached, return/report partial coverage with retrieved
     count and safety limit.
   - Never silently truncate and never classify a partially fetched date as
     fully covered.

5. Add explicit retrieval metadata.
   - Return a typed retrieval result with articles, requested selection,
     covered source dates, empty source dates, incomplete source dates,
     retrieved count, and safety-limit state.
   - Leave pipeline persistence changes for U2-B, but make U2-A metadata ready
     to be carried into run metadata.

6. Backward compatibility and config migration.
   - Preserve existing `lookback_hours` and `max_results` in the legacy arXiv
     config so v0.1.0 config remains readable.
   - Add date-native defaults in a versioned config migration rather than
     destroying old values.
   - Normal UI will stop presenting legacy controls in U2-C/U2-G; U2-A only
     prepares domain/config behavior and tests.

7. Deterministic tests before candidate audit.
   - Single date.
   - Multiple explicit dates.
   - Contiguous range.
   - Duplicate explicit date normalization.
   - Ordering.
   - Empty/no-submission date.
   - Exact UTC date boundaries.
   - Timezone/date normalization.
   - Pagination.
   - Internal safety cap.
   - Safety cap cannot produce complete coverage.
   - arXiv duplicates across categories/pages.
   - Backward config migration.
   - Existing v0.1.0 tests remain green.

8. Live smoke before audit.
   - If network permits, run a bounded live arXiv source-date retrieval smoke
     for a recent date/latest available query.
   - If DNS/network remains blocked, record the sanitized environment failure
     and rely on deterministic source fixtures for candidate qualification.

9. Audit/freeze.
   - After U2-A candidate verification, launch a fresh independent read-only
     Auditor over the U2-A delta.
   - Repair BLOCKER/IMPORTANT findings within the bounded audit repair policy.
   - On PASS, update campaign docs, commit locally, and create local annotated
     tag `u2a-qualified`.

## U2-A Audit Log

- initial auditor: `01a00f89-de07-7a92-b5fe-36dd01c36845`.
- initial result: FAIL with one IMPORTANT finding.
- IMPORTANT: sparse `EXPLICIT_DATES` used a min-to-max submittedDate query span
  while the safety cap counted only retained selected-date articles, so
  intervening off-date rows could be scanned without tripping the safety cap.
- repair round 1: explicit non-contiguous date selections now fetch each
  selected UTC date with a per-date `submittedDate` query while maintaining a
  global safety cap; when the cap is exhausted, the current and remaining
  selected dates are marked incomplete, not covered.
- minor follow-up: added a duplicate same-id/different-category regression.
- re-auditor: `01a00f8e-1ae5-7f62-9d70-06fe7708d80c`.
- re-auditor result: PASS with no BLOCKER/IMPORTANT findings.
- re-auditor checks: `pytest` 166 passed; `ruff check .` PASS; strict `mypy`
  PASS; `compileall` PASS; `git diff --check` PASS.
- re-auditor OPTIONAL: add a separate raw API-row/page scan ceiling in a future
  hardening pass.

## U2-B Candidate Log

- implementation: added additive app-run date metadata in schema version 5.
- compatibility: legacy app-run rows default to `LEGACY` origin and empty date
  metadata rather than being reinterpreted.
- pipeline: `DateSelection` and `RunOrigin` now flow through the shared
  pipeline/service boundary.
- source boundary: added optional `DateNativeSourceAdapter` protocol so future
  source adapters can implement date selection additively.
- persistence: date selection, requested dates, covered dates, empty dates,
  incomplete dates, retrieval completeness, and safety limit are stored in
  `app_runs`, run snapshots, History entries, CLI status payloads, and JSON
  export.
- cache: article/profile semantic analysis cache remains unchanged, so repeated
  identical date runs reuse valid analyses while each run records immutable
  date metadata.
- deterministic verification: `pytest` 172 passed; `ruff check .` PASS;
  `mypy --strict src tests` PASS; `python -m compileall -q src tests` PASS;
  `git diff --check` PASS.
- initial auditor: `01a00f95-797f-7bf1-ba94-bb43b2cf663a`.
- initial result: FAIL with one IMPORTANT finding.
- IMPORTANT: if a date-native source failed before returning retrieval metadata,
  failed app-run rows persisted `retrieval_complete=1` and no
  requested/incomplete date metadata.
- repair round 1: date-native runs now precompute deterministic requested
  dates for single/range/explicit selections, initialize retrieval as incomplete
  until the source returns, and mark source failures before metadata as
  incomplete; latest-available failures remain unresolved but incomplete.
- repair tests: source failure before metadata, latest-available unresolved
  failure, and pipeline-expanded range metadata.
- re-auditor: `01a00f9a-2298-7322-871f-ce433e051611`.
- re-auditor result: PASS with no BLOCKER/IMPORTANT findings.
- re-auditor checks: `pytest` 174 passed; `ruff check .` PASS; strict
  `mypy` PASS; `compileall` PASS; `git diff --check` PASS.
