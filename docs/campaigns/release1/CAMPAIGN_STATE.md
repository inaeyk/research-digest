# Release 1 Campaign State

- current_substage: M4-A candidate audit
- status: ACTIVE
- current_git_head: 8861682832aea1c5cd7dd3d580adecd98cd809a5
- current_tags_at_head: m2-qualified
- current_branch: master
- local_remote_tracking: `master` tracks `origin/master` at `8861682832aea1c5cd7dd3d580adecd98cd809a5`
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
- skipped_campaigns: M3 additional source types; M5 full-paper reading; M6 long-term research memory
- active_campaign_scope: M4 automatic daily operation; M7 release engineering, upgradeability, and productization; first release candidate
- qualification_status: M4A_REAUDIT_PASS_READY_FREEZE
- audit_repair_round: 1
- last_deterministic_verification: M4-A repair round 1 full gate: `pytest` 73 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- last_live_verification: M4-A live Codex smoke attempted with isolated temporary SQLite DB and static one-article source; Research Digest service returned sanitized provider failure. Direct `codex exec` probe fails with default Codex home at initialization (`failed to initialize in-process app-server client: Read-only file system`) and with throwaway writable `CODEX_HOME` at outbound API transport (`Operation not permitted` / stream disconnected). No repo-local runtime DB was modified.
- migration_data_safety_status: no release1 migrations applied yet; repo-local `research_digest.sqlite3` remains ignored and must not be used for upgrade tests. During M4-A re-audit, a manual CLI smoke likely wrote one runtime run record to the ignored repo-local DB; a content-free `PRAGMA integrity_check` returned `ok`.
- deferred_minor_optional_findings: none
- next_permitted_action: perform freeze hygiene, commit, and tag `m4a-qualified`
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

Freeze criteria:

- fresh independent read-only M4-A audit PASS
- `pytest`, `ruff check .`, `mypy --no-incremental src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m4a-qualified`
