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
