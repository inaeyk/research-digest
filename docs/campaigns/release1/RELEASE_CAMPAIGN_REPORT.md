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

Data-safety note:

- During re-audit, the auditor reported one accidental manual CLI smoke without `RESEARCH_DIGEST_DB`; it likely wrote one runtime run record to ignored repo-local `research_digest.sqlite3`.
- The repository worktree and staged inventory are unaffected.
- A content-free SQLite `PRAGMA integrity_check` against the ignored repo-local DB returned `ok`.
