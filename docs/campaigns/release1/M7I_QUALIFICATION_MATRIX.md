# M7-I Release Qualification Matrix

This matrix is the durable M7-I checklist/harness for installability, upgradeability,
recoverability, and operability. M7-I is not a feature-development stage.

Status values:

- PASS: executed successfully in this campaign state.
- DETERMINISTIC PASS: covered by deterministic tests/harness where live execution is not required.
- ENVIRONMENT BLOCKED: attempted, but this execution environment prevents completion.
- PENDING: not yet executed or not yet audited.

## Summary

- current stage: M7-I audit PASS ready to freeze
- base qualified tag: `m7h-qualified`
- current package version observed by `python -m pip show research-digest`: `0.1.0`
- package build backend: repo-local pure-Python PEP 517 backend `_research_digest_build`
- package build/install evidence: offline wheel build, isolated fresh-venv no-dependency install, documented editable `".[dev]"` install with no dependency download, installed `research-digest` console script smoke, `dev` extra metadata, and direct wheel-content cache/bytecode exclusion checks all PASS.
- package dependency limitation: full dependency download from PyPI remains network-dependent and may be blocked by the same DNS limitation observed earlier.
- network limitation: arXiv DNS resolution fails in this environment, including after network escalation.
- socket limitation: local server socket creation fails with `Operation not permitted`, including after sandbox escalation.
- scheduler limitation: Windows Task Scheduler/WSL interop fails with `UtilBindVsockAnyPort ... socket failed 1`.
- Codex limitation: Codex CLI is installed, but model execution cannot reach OpenAI endpoints from this environment.

## Matrix

| Case | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| 1 Fresh install | Isolated no DB/config startup initializes config, DB, schema, and CLI status. | `tests/test_release_qualification_matrix.py::ReleaseQualificationMatrixTests::test_fresh_install_like_environment_initializes_config_db_and_cli` | DETERMINISTIC PASS |
| 1 Fresh install package | Package installs and CLI exists without development checkout on `PYTHONPATH`. | Offline `pip wheel . --no-deps`; isolated fresh venv installs wheel with `--no-deps`; installed `research-digest --version` and `status --json` run from `/tmp`. | PASS for package build and installed CLI; full dependency download remains environment-dependent. |
| 2 M2 upgrade | Copy representative M2-qualified data and verify profiles/source settings/articles/analyses/feedback/runs survive migration. | `tests/test_release_qualification_matrix.py::...::test_m2_style_upgrade_repeated_startup_and_backup_preserve_data` now hand-builds the M2 schema with no `schema_metadata` or run snapshot tables, then verifies migration backup, schema version, counts, fingerprint preservation, and backup/export. | DETERMINISTIC PASS |
| 3 Repeated startup | Reopen upgraded DB without duplicate migrations or duplicate semantic data. | Same M7-I harness test compares semantic counts before/after reopen. | DETERMINISTIC PASS |
| 4 Codex unavailable | Codex configured but executable/auth unavailable gives bounded sanitized doctor/status/run behavior and preserves DB. | M7-I harness patches `shutil.which` unavailable and verifies provider failure with no secrets; existing CLI/service/lifecycle tests cover sanitized run failure and DB integrity. | DETERMINISTIC PASS |
| 5 Live Codex authenticated | Small real subscription-backed Codex digest over arXiv through persistence/history. | `codex --version` succeeds; `codex exec` with default home fails on read-only home; with writable `CODEX_HOME`, fails connecting to OpenAI endpoints. arXiv DNS also fails. | ENVIRONMENT BLOCKED |
| 6 Network unavailable | Bounded network failure, sanitized error, failed run record, DB integrity, later retry. | M7-I harness verifies sanitized doctor network failure; `tests/test_run_lifecycle.py` verifies sanitized failed run, DB integrity, retry, and cache reuse. | DETERMINISTIC PASS |
| 7 Scheduled headless run | Supported WSL2/Windows schedule invokes installed CLI, no Streamlit dependency, inspectable status, no secrets in task command. | Existing scheduler tests cover command construction, idempotency, secret exclusion, and status. Live `research-digest schedule status --json` attempted. | DETERMINISTIC PASS; live scheduler ENVIRONMENT BLOCKED by WSL socket failure. |
| 8 Overlap manual/scheduled | M4-C exclusion prevents duplicate/racing execution and stale recovery remains valid. | `tests/test_run_lifecycle.py` simultaneous exclusion and stale recovery tests. | DETERMINISTIC PASS |
| 9 Code upgrade | Code is replaceable; user data/config survive reinstall/upgrade. | M7-A data/config separation tests, M7-I M2-qualified adoption/reopen harness, and isolated no-dependency package install from both wheel and source tree. | DETERMINISTIC PASS for data/config invariant; package install PASS for package/CLI, full dependency download remains environment-dependent. |
| 10 Migration failure | Controlled migration failure creates backup where required, fails closed, and leaves data recoverable. | `tests/test_db.py` migration failure/backup tests. | DETERMINISTIC PASS |
| 11 Backup | `research-digest backup`, validated SQLite snapshot, JSON export, reserved path handling, collisions, no secrets. | M7-G tests plus M7-I harness backup from upgraded DB with `?` and `#` in output path. | DETERMINISTIC PASS |
| 12 Serve/port conflict | `research-digest serve` handles occupied preferred port and prints actual URL. | CLI serve test and M7-I harness with mocked occupied port. Direct serve smoke attempted. | DETERMINISTIC PASS; live listener ENVIRONMENT BLOCKED by local socket restriction. |

## Commands And Results

Deterministic M7-I harness:

- `pytest tests/test_release_qualification_matrix.py`: 6 passed.
- `ruff check _research_digest_build.py tests/test_release_qualification_matrix.py pyproject.toml`: PASS.
- `mypy --strict tests/test_release_qualification_matrix.py`: PASS.

Packaging:

- Initial candidate `python -m pip wheel . --no-deps -w /tmp/research-digest-wheelhouse`: FAIL, could not resolve external build dependency `hatchling` from PyPI due DNS.
- Repair round 1 replaced the external build backend with repo-local `_research_digest_build` for this pure-Python package.
- `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-package.CtC0I9/wheelhouse`: PASS, created `research_digest-0.1.0-py3-none-any.whl`.
- isolated fresh venv `pip install --no-deps /tmp/research-digest-m7i-package.CtC0I9/wheelhouse/research_digest-0.1.0-py3-none-any.whl`: PASS.
- installed wheel CLI `/tmp/research-digest-m7i-package.CtC0I9/venv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- installed wheel metadata entry point query: PASS, `research_digest.cli:main`.
- installed wheel CLI `status --json` with isolated data/config from `/tmp`: PASS, initialized schema version 4 and config version 1; scheduler warning sanitized.
- isolated fresh source install `pip install --no-deps .`: PASS.
- installed source CLI `/tmp/research-digest-m7i-package.CtC0I9/sourcevenv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- `python -m pip show research-digest`: PASS in current venv; editable install version `0.1.0`.

Post-repair full gate:

- full `pytest`: 144 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- final current-state `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-finalpkg2.VfZt6V/wheelhouse`: PASS.
- final isolated fresh-venv wheel install with `--no-deps`: PASS.
- final installed CLI `/tmp/research-digest-m7i-finalpkg2.VfZt6V/venv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- final installed CLI `status --json` with isolated data/config from `/tmp`: PASS, schema version 4 and config version 1 initialized; scheduler warning sanitized.
- final installed entry point metadata query: PASS, `research_digest.cli:main`.
- final wheel-content cache/bytecode check: PASS, no `__pycache__` or `.pyc` members.

Closure audit and installability repair:

- Fresh independent M7-I closure Auditor returned FAIL with one IMPORTANT finding after confirming the two earlier BLOCKERs were closed.
- IMPORTANT: the repo-local PEP 517 backend did not support the README-documented editable install path `pip install -e ".[dev]"`, and the generated package metadata omitted the `dev` extra.
- Repair added PEP 660 editable hooks and `Provides-Extra`/extra-scoped `Requires-Dist` metadata to `_research_digest_build`.
- `pytest tests/test_release_qualification_matrix.py`: 6 passed, including documented editable install and wheel metadata regression coverage.
- `ruff check _research_digest_build.py tests/test_release_qualification_matrix.py pyproject.toml`: PASS.
- strict `mypy --strict tests/test_release_qualification_matrix.py`: PASS.
- full `pytest`: 145 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- final current-state `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-finalpkg3.RhYfM6/wheelhouse`: PASS.
- final wheel-content cache/bytecode check: PASS, no `__pycache__` or `.pyc` members.
- final wheel metadata: PASS, entry point `research_digest.cli:main`, `Provides-Extra: dev`, and `Requires-Dist` entries for `mypy`, `pytest`, and `ruff` under `extra == "dev"`.
- final isolated wheel install with `--no-deps`: PASS.
- final installed wheel CLI `/tmp/research-digest-m7i-finalpkg3.RhYfM6/wheelvenv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- final installed wheel CLI `status --json` with isolated data/config from `/tmp`: PASS, schema version 4 and config version 1 initialized; scheduler warning sanitized.
- final documented editable install `pip install -e '.[dev]' --no-deps`: PASS.
- final editable install CLI `/tmp/research-digest-m7i-finalpkg3.RhYfM6/editablevenv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.

Second closure audit:

- Fresh independent read-only M7-I Auditor returned PASS with no BLOCKER/IMPORTANT/MINOR/OPTIONAL findings.
- Auditor verified both original M7-I BLOCKERs remain closed and the editable/dev install IMPORTANT finding is closed.
- Auditor judged environment-blocked live Codex/arXiv/scheduler/serve evidence acceptable for M7-I because deterministic behavior is covered and limitations are concrete.

Runtime/live probes:

- `which codex`: PASS, `/home/inaeyk/.nvm/versions/node/v22.22.2/bin/codex`.
- `codex --version`: PASS, `codex-cli 0.147.0`.
- `codex exec --skip-git-repo-check 'Reply with exactly: codex-ok'`: FAIL, default Codex home initialization hits read-only filesystem.
- `CODEX_HOME=/tmp/rd-codex-home codex exec --skip-git-repo-check 'Reply with exactly: codex-ok'`: FAIL, OpenAI endpoint connection blocked with `Operation not permitted`.
- arXiv reachability probe with 10-second timeout: FAIL, DNS temporary failure.
- arXiv reachability probe after network escalation: FAIL, same DNS temporary failure.
- `python -m research_digest.cli schedule status --json`: FAIL, sanitized WSL Task Scheduler socket failure.
- `python -m research_digest.cli serve --port 18601`: FAIL, sanitized local socket `Operation not permitted`.
- temp-path `python -m research_digest.cli status --json`: PASS.
- `python -m research_digest.cli doctor --json`: PASS with sanitized environment warnings and no failures.
- `python -m research_digest.cli --version`: PASS, `research-digest 0.1.0`.

## Deferred To Final Release-Candidate Verification

The final release-candidate gate must rerun package build/install and live Codex/arXiv digest if the environment permits. If the same DNS/socket/OpenAI transport limits persist, the final report must carry those exact limitations into the human review packet rather than silently treating them as product PASS.
