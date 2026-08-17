# Final Release-Candidate Verification

Status: final release audit pending.

Verification workspace: `/tmp/research-digest-rc.Q4O1FA`.

Final release-candidate commit after final-audit MINOR documentation follow-up: `eadedb71b7a64302edb6ac6b7d1fbfe1d6bfbe95`.

Release-candidate packet commit before final-audit MINOR documentation follow-up: `f8d87eda5048c111d5d754c2e089ef3a33254508`.

M7-I qualified base: `efc4c88a689d06dc0e4b4428605c05836ddb7374` (`m7i-qualified`).

## Version And Tag Recommendation

- package version in `pyproject.toml`: `0.1.0`
- runtime `research_digest.__version__`: `0.1.0`
- existing public-style `v*` tags: none
- suggested human-reviewed public tag: `v0.1.0`

No public release tag, remote push, GitHub release, or package publication was performed.

## Deterministic Gate

- full `pytest`: 145 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- targeted recovery/cache/migration/backup slice `pytest tests/test_pipeline.py tests/test_run_lifecycle.py tests/test_db.py tests/test_backup.py tests/test_config.py`: 51 passed.

## Package Build And Install

- `python -m pip wheel . --no-deps -w /tmp/research-digest-rc.Q4O1FA/wheelhouse`: PASS, created `research_digest-0.1.0-py3-none-any.whl`.
- wheel content check: PASS, no `__pycache__` or `.pyc` members.
- wheel metadata check: PASS, includes `Provides-Extra: dev`.
- wheel entry point check: PASS, `research-digest = research_digest.cli:main`.
- isolated fresh venv wheel install with `--no-deps`: PASS.
- isolated editable install `pip install -e '.[dev]' --no-deps`: PASS.
- installed wheel CLI `research-digest --version`: PASS, `research-digest 0.1.0`.
- installed editable CLI `research-digest --version`: PASS, `research-digest 0.1.0`.

Full dependency download from PyPI was not reattempted after earlier DNS failures; the release metadata declares dependencies, and no-dependency packaging smokes verify local build/install/entry points.

## Installed CLI And Data Initialization

Installed wheel CLI with isolated data/config:

- `research-digest status --json`: PASS.
- initialized DB path: `/tmp/research-digest-rc.Q4O1FA/data/research_digest.sqlite3`.
- initialized config path: `/tmp/research-digest-rc.Q4O1FA/config/config.json`.
- schema version: `4`.
- config version: `1`.
- scheduler status: sanitized WSL Task Scheduler socket warning.

Installed wheel CLI doctor:

- `research-digest doctor --json`: PASS with `failure_count: 0`.
- warnings: scheduler interop unavailable; no digest runs recorded; network checks skipped.

## Live Codex And Network Evidence

Disposable live-smoke DB:

- data dir: `/tmp/research-digest-rc.Q4O1FA/live-data`.
- config dir: `/tmp/research-digest-rc.Q4O1FA/live-config`.
- one enabled profile: `Release smoke gravity`.
- arXiv source enabled with category `hep-th`, lookback `24`, max results `1`.

Installed live digest:

- `research-digest run --json`: FAIL, bounded and sanitized: `could not reach arXiv API: [Errno -3] Temporary failure in name resolution`.
- same command after sandbox escalation: FAIL with the same DNS result.
- status after attempts: PASS; last run is recorded as `FAILED`; DB remains valid.
- `doctor --json --network --network-timeout 5`: FAIL only because last run failed; arXiv network check is a WARNING with the same DNS result.
- same doctor network command after sandbox escalation: same result.

Codex CLI:

- `which codex`: PASS, `/home/inaeyk/.nvm/versions/node/v22.22.2/bin/codex`.
- `codex --version`: PASS, `codex-cli 0.147.0`.
- `CODEX_HOME=/tmp/research-digest-rc.Q4O1FA/codex-home codex exec --skip-git-repo-check 'Reply with exactly: codex-ok'`: FAIL after bounded retries; websocket and HTTPS transport to OpenAI endpoints are blocked with `Operation not permitted` / request send errors.
- same Codex command after sandbox escalation: same result.

The final small live Codex-backed digest could not complete because arXiv DNS failed before analysis. The Codex model probe also could not reach OpenAI transport. These are recorded as environment-blocked live evidence, not product PASS.

## Scheduler And Serve Evidence

Scheduler:

- `research-digest schedule status --json`: FAIL with sanitized WSL Task Scheduler socket error: `UtilBindVsockAnyPort ... socket failed 1`.
- deterministic scheduler tests cover stable installed CLI invocation, idempotency, status, no Streamlit dependency, and no secrets in scheduled command lines.

Serve:

- installed `research-digest serve --port 18601`: FAIL with sanitized local socket `[Errno 1] Operation not permitted`.
- same serve command after sandbox escalation: same result.
- deterministic serve tests cover occupied-port fallback and printed usable URL.

## Backup And Recovery Evidence

Installed CLI backup:

- `research-digest backup --json --export-json --output /tmp/research-digest-rc.Q4O1FA/final-backup.sqlite3`: PASS.
- backup path: `/tmp/research-digest-rc.Q4O1FA/final-backup.sqlite3`.
- JSON export path: `/tmp/research-digest-rc.Q4O1FA/final-backup.export.json`.
- schema version: `4`.
- `PRAGMA integrity_check`: `ok`.
- backup contains one profile and two bounded failed run records from the live-smoke attempts.
- JSON export validates with `python -m json.tool`.
- JSON export contains no secrets or authentication material.

## Secret And Runtime-File Hygiene

- `git ls-files` found no tracked `.env`, SQLite DB, virtualenv, cache, `.codex`, or `.codegraph` paths.
- secret-pattern scan found only fake redaction-test strings in tests and known documentation references; no real credentials or runtime auth material were found.
- worktree currently contains release-candidate documentation changes only after the M7-I qualification commit.

## Known Environment Limitations To Carry Forward

- arXiv DNS resolution fails even after sandbox escalation.
- Codex model transport to OpenAI endpoints fails even after sandbox escalation.
- WSL Task Scheduler interop fails with socket errors in this environment.
- local serve socket probing fails with `Operation not permitted` even after sandbox escalation.
- PyPI dependency download was previously DNS-blocked; no-dependency wheel/editable install paths pass.

## Final Audit

Fresh independent final release audit over `m2-qualified..f8d87eda5048c111d5d754c2e089ef3a33254508`: PASS WITH MINOR FINDINGS.

MINOR follow-up applied after audit:

- corrected release bookkeeping to distinguish the M7-I base from the actual release-candidate commit.
- clarified README and human packet upgrade/backup sequencing for older repo-local M2 development databases.

Final human-stop state records `eadedb71b7a64302edb6ac6b7d1fbfe1d6bfbe95` as the exact release-candidate commit.
