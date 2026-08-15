# Release 1 Campaign State

- current_substage: M4-B candidate audit
- status: ACTIVE
- current_git_head: 82b8a7e82c047c9dff96d075f7f8b9981fa9f312
- current_tags_at_head: m4a-qualified
- current_branch: master
- local_remote_tracking: `master` tracks `origin/master`; local branch is 1 commit ahead after M4-A freeze
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
- m4a_qualified_commit: 82b8a7e82c047c9dff96d075f7f8b9981fa9f312
- m4a_qualified_tag: m4a-qualified
- m4a_qualified_tag_object: 99a1d7388903f11ef678b528d0879c7d33c25044
- skipped_campaigns: M3 additional source types; M5 full-paper reading; M6 long-term research memory
- active_campaign_scope: M4 automatic daily operation; M7 release engineering, upgradeability, and productization; first release candidate
- qualification_status: M4B_CANDIDATE_READY_AUDIT
- audit_repair_round: 0
- last_deterministic_verification: M4-B candidate self-repair full gate: `pytest` 85 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- last_live_verification: M4-B live scheduler status smoke attempted with `python -m research_digest.cli schedule status --task-name 'Research Digest Codex Smoke' --json`; returned sanitized Windows interop failure `UtilBindVsockAnyPort ... socket failed 1` both inside the default sandbox and after sandbox escalation. Earlier direct `powershell.exe` probe had the same failure. No Task Scheduler task was installed or removed.
- migration_data_safety_status: no release1 migrations applied yet; repo-local `research_digest.sqlite3` remains ignored and must not be used for upgrade tests. During M4-A re-audit, a manual CLI smoke likely wrote one runtime run record to the ignored repo-local DB; a content-free `PRAGMA integrity_check` returned `ok`.
- deferred_minor_optional_findings: none
- next_permitted_action: complete fresh M4-B audit; repair BLOCKER/IMPORTANT findings if any; otherwise freeze, commit, and tag `m4b-qualified`
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
- freeze: committed `82b8a7e82c047c9dff96d075f7f8b9981fa9f312` (`Qualify M4-A headless execution`) and created local annotated tag `m4a-qualified` with tag object `99a1d7388903f11ef678b528d0879c7d33c25044`.

## M4-B Frozen Specification

Goal: allow automatic daily operation without Streamlit by installing an OS-backed schedule that invokes the qualified M4-A headless command.

Supported first-release backend:

- WSL2 on Windows through Windows Task Scheduler.
- Future Linux cron/systemd and macOS launchd support must be additive backend implementations, not digest-engine changes.
- The scheduling layer must be separate from `research_digest.service` and must not call pipeline code directly.

CLI surface:

- Add a small scheduling command group under `research-digest schedule`.
- Required operations for the Windows backend: `status`, `install`, `remove`.
- `install` is idempotent: if the named task exists, update it to the requested configuration.
- `remove` is idempotent: removing a missing task succeeds with an explicit not-installed result.
- `status` is inspectable and has a JSON option.

Resolved execution target:

- Scheduled task action must ultimately execute `wsl.exe -d <distro> --cd <working-dir> --exec env ... research-digest run`.
- Use the installed `research-digest` command as the stable target; do not schedule Streamlit or a Python source-file path.
- Resolve WSL distro from `WSL_DISTRO_NAME` unless explicitly overridden.
- Resolve working directory deliberately from the current repository path for this release. M7-A will move persistent data/config to platform user directories.
- Resolve data path deliberately. If `RESEARCH_DIGEST_DB` is set, schedule that absolute path. Otherwise schedule the current configured/default DB path as an absolute path.

Secrets and environment:

- Do not place `OPENAI_API_KEY`, Codex auth files, or other secrets in the task command.
- It is acceptable to set non-secret `RESEARCH_DIGEST_DB` and analyzer/provider selection variables needed to preserve runtime behavior.
- Codex saved ChatGPT authentication remains external to Research Digest and is not embedded in scheduler configuration.

Timezone and DST:

- Windows Task Scheduler daily triggers are interpreted in the Windows local timezone and follow Windows daylight-saving behavior.
- The CLI must document/report that behavior in schedule status/install output.
- Store requested local time as `HH:MM` and validate it deterministically.

Failure visibility:

- The scheduled command must invoke `research-digest run`; M4-A exit codes make failures visible to Task Scheduler LastTaskResult.
- Status must surface Task Scheduler state, last run time/result, and next run time when available.
- M4-C will add stronger durable run lifecycle/overlap semantics; M4-B must not implement a custom daemon or lock manager.

Tests required before M4-B freeze:

- command construction quotes/escapes arguments safely and excludes secrets
- WSL distro/data path/working directory resolution
- daily time validation and Windows local timezone/DST explanation
- install/update/remove/status idempotent behavior via mocked PowerShell runner
- unsupported non-WSL/Windows backend failure is clear and sanitized
- CLI status/install/remove JSON and human output are deterministic
- existing M4-A run and M2 deterministic tests remain green

Live verification required before M4-B freeze:

- If Windows interop is available, perform a real Task Scheduler smoke using a non-production test task name and a manual trigger/removal cycle.
- If PowerShell/Task Scheduler interop is blocked by this execution environment, record the exact sanitized failure and complete only if deterministic backend tests cover command generation and idempotent operations.

## M4-B Candidate Log

- implementation: added `research_digest.scheduler` with a Windows Task Scheduler backend, explicit schedule request model, WSL command construction, explicit `wsl.exe` and installed `research-digest` executable resolution, non-secret scheduled environment construction, time validation, status parsing, and idempotent install/remove behavior.
- CLI: added `research-digest schedule status|install|remove` with `--json`, task-name selection, backend selection, install time validation, and WSL distro override.
- docs: README documents `research-digest run` and WSL2 scheduling commands.
- self-review repair before audit completion: scheduler install now resolves the Windows `wsl.exe` executable and the installed `research-digest` command deliberately; if `research-digest` is not on PATH, install fails clearly instead of creating a broken schedule.
- deterministic verification: `pytest` 85 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live verification: Windows interop/Task Scheduler smoke is blocked in this session by `UtilBindVsockAnyPort ... socket failed 1`; CLI surfaces that as sanitized JSON failure. No scheduler task was created.

Freeze criteria:

- fresh independent read-only M4-B audit PASS
- `pytest`, `ruff check .`, `mypy --no-incremental src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m4b-qualified`
