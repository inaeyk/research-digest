# M2 Campaign Report

## M2-A Recovery

- baseline: current HEAD 839a3ef0f0cc31a8371c24680de254cbd5f84377 is tagged `m2a-qualified`, with clean tracked source state before campaign docs were added.
- deterministic recovery checks: `pytest` passed 48 tests; `ruff check .` passed; `mypy src` passed; `compileall -q src tests` passed; `git diff --check` passed.
- hygiene: local SQLite database, virtualenv, caches, and agent/tool directories are ignored.
- auditor: fresh read-only auditor `01a00422-e371-76a2-9712-eb70522eac96`.
- auditor result: NOT QUALIFIED.
- important defect: Today session signatures include profile semantics, but persisted full analyses are still keyed only by article/profile id. A rerun after editing the same profile id can reuse stale analysis generated under the old profile name, description, or threshold.
- minor auditor note: `mypy --no-incremental src tests` reported a test double type mismatch in `tests/test_pipeline.py`.
- disposition: M2-A requires narrow repair before any qualified freeze can stand. Existing local `m2a-qualified` tag currently points at an unqualified commit and must be corrected only after successful repair, deterministic checks, and fresh independent closure audit.

### Repair Round 1

- worker: `01a00425-784e-71b3-bd6c-95a8492627e6`.
- repair: full relevance-analysis cache identity now includes a deterministic profile semantic fingerprint derived from profile id, name, description, and relevance threshold.
- migration: legacy `relevance_analyses` rows without profile fingerprints are retained under `legacy:<analysis_id>` fingerprints so unverifiable old rows are not reused as current-profile analyses.
- tests added: same-profile semantic reuse, same-id name/description/threshold invalidation, legacy migration retention/non-reuse, and typed analyzer test double.
- local deterministic verification: `pytest` passed 51 tests; `ruff check .` passed; `mypy --no-incremental src tests` passed; `compileall -q src tests` passed; `git diff --check` passed.
- local smoke: targeted same-profile-id cache probe showed first run NEW, identical semantic rerun REUSED, edited description/threshold rerun NEW.
- closure auditor: fresh read-only auditor `01a0042b-d8df-7e00-8b61-0447f9299688`.
- closure auditor result: PASS with no findings.
- auditor verification: 51 tests passed; ruff passed; strict no-incremental mypy over `src tests` passed; compileall passed; `git diff --check` passed; targeted cache/index smoke passed.
- status: qualified, but commit/tag correction blocked by read-only `.git`.

### Human Stop

- blocker: `.git` is mounted read-only in this session.
- evidence: `git add ...` failed with `fatal: Unable to create '/home/inaeyk/researchrepo/research-digest/.git/index.lock': Read-only file system`; mount inventory shows `.git` mounted `ro`.
- current HEAD/tag: HEAD remains 839a3ef0f0cc31a8371c24680de254cbd5f84377 and local `m2a-qualified` still points there.
- uncommitted qualified files: `src/research_digest/models.py`, `src/research_digest/db.py`, `src/research_digest/pipeline.py`, `src/research_digest/ui/pages/today.py`, `tests/test_db.py`, `tests/test_pipeline.py`, and `docs/campaigns/m2/`.
- recommended next action: rerun with writable `.git`, then stage these files, commit repaired M2-A, and move local `m2a-qualified` to the new commit before starting M2-B.

### Freeze Completed

- replacement custodian verified the working tree matched the qualified repair record before staging.
- resumed deterministic verification: `pytest` 51 passed; `ruff check .` passed; `mypy --no-incremental src tests` passed; `compileall -q src tests` passed; `git diff --check` passed.
- staged inventory: only the six recorded source/test files plus `docs/campaigns/m2/CAMPAIGN_STATE.md` and `docs/campaigns/m2/M2_CAMPAIGN_REPORT.md`.
- excluded inventory: `research_digest.sqlite3`, `.venv`, `.env`, caches, and local agent/runtime state remained ignored and unstaged.
- qualified commit: `81d4d5e011c46650c6094db628668e82a030547e`.
- local annotated tag: `m2a-qualified` points to `81d4d5e011c46650c6094db628668e82a030547e`; tag object `e4f09071a4c7f04f5ad9d3238942b2ffbf42a5f0`.

## M2-B Two-Stage Abstract Preselection

- implementation: added deterministic `TermOverlapPreselector` behind an `AbstractPreselector` protocol.
- behavior: cache hits are preserved before preselection; only cache-miss articles are preselected for full LLM analysis.
- stages: title/category term overlap first, then abstract term overlap; profiles that produce no useful terms fail open by selecting all cache misses.
- observability: `DigestResult`, app-run history, and Today metrics now report selected and skipped new-analysis counts.
- migration: legacy `app_runs` tables gain `preselected_count` and `skipped_analysis_count` with `NOT NULL DEFAULT 0`.
- tests added: skipped cache-miss behavior, reused-analysis preservation, preselector stage/fallback behavior, and legacy app-run count migration.
- local deterministic verification: `pytest` passed 57 tests; `ruff check .` passed; `mypy --no-incremental src tests` passed; `compileall -q src tests` passed; `git diff --check` passed.
- fresh independent auditor: `01a00453-cf34-7463-b64b-e8ed9766a0c2`.
- auditor result: PASS with no blocking findings.
- qualified commit: `9aea33b0a1dc8a2b34ad7622e55bb8fb047852bb`.
- local annotated tag: `m2b-qualified` points to `9aea33b0a1dc8a2b34ad7622e55bb8fb047852bb`; tag object `0a81deaf52d6d4ffa49659b59a7decbd87fd2905`.

## M2-C Feedback And Calibration

- implementation: added per-article feedback keyed by article id, profile id, and profile semantic fingerprint.
- calibration: added deterministic calibration summaries comparing feedback labels against the active threshold.
- UI: Today page shows a feedback segmented control per analyzed paper and a feedback calibration panel when feedback exists.
- tests added: feedback persistence/profile-semantic isolation, calibration confusion counts, and first feedback selection visibility to rebuilt calibration.
- first auditor: `01a0045b-aa55-7623-bb67-2c0bfee29472`.
- first auditor result: NOT QUALIFIED; calibration rendered one rerun behind after first feedback selection and campaign state had stale M2-B freeze wording.
- repair: changed feedback writes to request an immediate Streamlit rerun after successful persistence and corrected campaign state.
- local deterministic verification after repair: `pytest` passed 61 tests; `ruff check .` passed; `mypy --no-incremental src tests` passed; `compileall -q src tests` passed; `git diff --check` passed.
- closure auditor: `01a0045f-bf9d-7533-a564-000e526bb57b`.
- closure auditor result: PASS with no blocking findings.
- qualified commit: `f6cbe703ae41657120105237fab221f56c2dc9e4`.
- local annotated tag: `m2c-qualified` points to `f6cbe703ae41657120105237fab221f56c2dc9e4`; tag object `bdcba8f788ad09f6e40d233b6a50d9a7a94335fb`.

## M2-D Daily Cross-Paper Synthesis

- implementation: added deterministic cross-paper synthesis over analyzed digest items.
- behavior: synthesis uses above-threshold papers only, counts category coverage, highlights high-priority papers, and surfaces recurring matched topics across multiple relevant papers.
- UI: Today page renders a cross-paper synthesis panel above the per-paper result list when relevant papers exist.
- tests added: relevant-only synthesis, recurring topic counts, high-priority title extraction, and empty-signal behavior.
- local deterministic verification: `pytest` passed 63 tests; `ruff check .` passed; `mypy --no-incremental src tests` passed; `compileall -q src tests` passed; `git diff --check` passed.
- first auditor: `01a00463-9a7c-76d0-a5cf-2dfa621e8d87`.
- first auditor result: NOT QUALIFIED; duplicate matched topics within one relevant paper could be counted as a recurring cross-paper topic.
- repair: normalized matched topics are deduplicated per paper before recurring-topic counts are computed.
- local deterministic verification after repair: `pytest` passed 64 tests; `ruff check .` passed; `mypy --no-incremental src tests` passed; `compileall -q src tests` passed; `git diff --check` passed.
- closure auditor: `01a00466-0aa7-76a3-b043-928006752fab`.
- closure auditor result: PASS for synthesis code repair; metadata-only campaign-state findings corrected before freeze.
- status: qualified; commit/tag freeze pending.
