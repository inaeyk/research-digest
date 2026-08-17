# Release 1 Campaign State

- current_substage: release-candidate scheduler live smoke
- status: RC_SCHEDULER_LIVE_SMOKE_AWAITING_HUMAN
- current_git_head: scheduler repair live-smoke bookkeeping commit containing this state; verify with `git rev-parse HEAD`
- prior_release_candidate_commit: eadedb71b7a64302edb6ac6b7d1fbfe1d6bfbe95
- scheduler_environment_repair_commit: 6570aa37dc7c055828977cd490063fb160d08445
- release_candidate_commit: pending human live scheduler smoke after committed scheduler repair
- current_tags_at_head: none
- current_branch: master
- local_remote_tracking: `master` tracks `origin/master`; local branch will be 18 commits ahead after scheduler repair live-smoke bookkeeping
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
- m4b_qualified_commit: 9d7db2ce0983e8fa1a68534450b890ae110ebed8
- m4b_qualified_tag: m4b-qualified
- m4b_qualified_tag_object: 2c204f177d7ace500766365fc49d780ad08d8ceb
- m4c_qualified_commit: 2c232fa163c67d8af87e3d039affd11187a5c814
- m4c_qualified_tag: m4c-qualified
- m4c_qualified_tag_object: 256cdd6348dc76c05a92dc33d602ee691498ab5c
- m4d_qualified_commit: ee280f439b9df3d5478779e33dd55995dabcc9fc
- m4d_qualified_tag: m4d-qualified
- m4d_qualified_tag_object: 0ae15c90d886fd9d03c3cf8d3c4f519fc57b5955
- m7a_qualified_commit: 62d6ed4a3902a929d94d6612edc74af0a18cd7a1
- m7a_qualified_tag: m7a-qualified
- m7a_qualified_tag_object: 7a8e3da4ffa79570b5d6748f43a2a586a2268b5e
- m7b_qualified_commit: 73b549a75d372ad754f2a90f5c6aae788c7434fa
- m7b_qualified_tag: m7b-qualified
- m7b_qualified_tag_object: ad09bde4eb4a6103e147e729c4bb0024d6bd19a6
- m7c_qualified_commit: 246b1fee3a983e5da88e54c8f67850d0a6d3fa4f
- m7c_qualified_tag: m7c-qualified
- m7c_qualified_tag_object: 1c8f5c66d3b0b217057f39af53a3e210288db0fd
- m7d_qualified_commit: 2c1f9feb5ca95accf28527b0956727bb275642d0
- m7d_qualified_tag: m7d-qualified
- m7d_qualified_tag_object: e02247e1796fab983d220916f6db73a8c7056ffd
- m7e_qualified_commit: 262bdd84be0c634c0b254e325c54304c0e840eb7
- m7e_qualified_tag: m7e-qualified
- m7e_qualified_tag_object: 5e46f46ec355391f7ee479d565855025cfa1db94
- m7f_qualified_commit: 478f4d8582a2e3c9ad7b114fcfb4301253b1a961
- m7f_qualified_tag: m7f-qualified
- m7f_qualified_tag_object: 68746dba9d860cb53b3682ccc19d82b087411984
- m7g_qualified_commit: 4070cce4744fc0862e418b1db51f43019fb0a78c
- m7g_qualified_tag: m7g-qualified
- m7g_qualified_tag_object: 1a11880d39ba71aed06163620142eeca0aaa372f
- m7h_qualified_commit: e972d95933fc8145924883f0fa29cfeec52d4600
- m7h_qualified_tag: m7h-qualified
- m7h_qualified_tag_object: 4a1b6ab618265a15f9c99682e4d638583f362c32
- m7i_qualified_commit: efc4c88a689d06dc0e4b4428605c05836ddb7374
- m7i_qualified_tag: m7i-qualified
- m7i_qualified_tag_object: ec016b565fe84857b8053c51822290025b50c0db
- skipped_campaigns: M3 additional source types; M5 full-paper reading; M6 long-term research memory
- active_campaign_scope: M4 automatic daily operation; M7 release engineering, upgradeability, and productization; first release candidate
- qualification_status: RC_SCHEDULER_CODEX_PATH_REPAIR_AUDIT_PASS_AWAITING_HUMAN_LIVE_SMOKE
- audit_repair_round: 2
- last_deterministic_verification: RC scheduler PATH repair gate after audit documentation updates: full `pytest` 149 passed; `ruff check .` PASS; strict `mypy --strict src tests` PASS; `python -m compileall -q src tests` PASS; `git diff --check` PASS.
- last_live_verification: Final RC package/install/CLI/backup smokes PASS from `/tmp/research-digest-rc.Q4O1FA`; live arXiv digest, Codex model transport, WSL scheduler, and serve listener remain environment-blocked with sanitized bounded failures even after escalation where applicable.
- migration_data_safety_status: M7-B candidate adds explicit schema version metadata, ordered migrations, backup before schema-changing upgrades of existing DBs, rollback on failed migration, and visible migration backup path. Repo-local `research_digest.sqlite3` remains ignored and was not used for upgrade testing.
- deferred_minor_optional_findings: none; final release Auditor reported two MINOR documentation/bookkeeping findings and both were repaired before the earlier human stop.
- next_permitted_action: stop for the human live scheduler smoke in `docs/campaigns/release1/RC_SCHEDULER_LIVE_SMOKE.md`; do not declare final release candidate accepted until that smoke passes.
- human_stop_reason: human live Windows Task Scheduler smoke is required to verify `LastTaskResult == 0`, a new `COMPLETED` run, and no secrets in the generated task action.

## Restored Release Campaign Charter Authority

This section records the restored human release-campaign authority so future recovery does not depend on chat transcript context.

Campaign model:

- This is a supervised autonomous release campaign for M4 automatic daily operation, M7 release engineering/productization/upgradeability, and the first release candidate.
- M3 additional source adapters, M5 full-paper/deep reading, and M6 persistent research memory are explicitly out of scope for this release campaign.
- For each remaining substage, use the persistent Worker for implementation/repair, launch a fresh independent read-only Auditor for qualification, use bounded Worker/Auditor repair loops, run deterministic qualification before freeze, run live/runtime smoke tests where appropriate, update durable campaign state/report at meaningful boundaries, and commit/tag only qualified substages.
- The default audit-repair budget is the initial candidate plus up to two audit-driven repair rounds per substage. Ordinary pre-audit test/fix iterations do not count against that budget.
- Do not weaken requirements or acceptance tests merely to obtain PASS.

Local commit/tag authority:

- The human authorizes local staging, local commits, and local annotated qualification tags for qualified M7-G, M7-H, M7-I, and release-candidate closeout bookkeeping.
- This release-campaign authority overrides the generic AGENTS.md requirement for explicit permission before local campaign commits/tags.
- Do not push release-campaign commits/tags, create the final public release/version tag, publish a GitHub release, publish a package, or perform the final public release without the final human release decision.

Human-stop conditions:

- Stop and request human authority only if requirements are materially ambiguous and different reasonable choices would change product behavior; a proposed repair requires changing the frozen release contract; a security or permission boundary must be weakened; a new paid/external service, credential, or external authorization is required; repository/data integrity or recovery state is unsafe or materially ambiguous; trustworthy Worker/Auditor evidence remains materially contradictory after inspection and testing; the bounded audit-repair budget for a substage is exhausted; or the final release-candidate gate is reached.
- Do not stop merely because tests fail, Streamlit fails, SQLite migration/backup code fails, Codex produces malformed output, scheduling fails, packaging fails, or a fresh Auditor finds an ordinary BLOCKER/IMPORTANT implementation defect. Those belong in the normal repair loop.

Remaining authorized substages:

- M7-G: backup/export qualification and freeze.
- M7-H: release UI and installation polish without adding M3/M5/M6 functionality.
- M7-I: release qualification matrix, not feature development.
- Release-candidate gate: prepare materials, run final verification and final Auditor, then stop at `RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN`.

M7-H authority:

- Goal: turn the qualified application into a coherent first-release user experience without adding M3/M5/M6 functionality.
- Desired release navigation is approximately Today, History, Interests, Sources, Settings.
- Settings may expose existing release functionality such as analyzer/provider selection/status, preselection fraction, schedule status/configuration, active data location, application version, schema/config version, and health/doctor summary.
- Streamlit must not duplicate CLI/business logic; it must use the same application/service/configuration boundaries already qualified elsewhere.
- Required release states: first run, empty digest, loading/running, no provider/Codex unavailable, failed run, stale result, history, and sources.
- Sources remain arXiv-first; do not add RSS, HTML, arbitrary APIs, or other M3 sources.
- Update README and release-facing documentation for installed CLI usage: `research-digest serve`, `research-digest run`, `research-digest status`, `research-digest doctor`, and `research-digest backup`.
- Documentation must cover installation, first run, ChatGPT/Codex CLI authentication, optional OpenAI API provider, data/config locations, manual digest, UI launch, daily schedule install/status/remove, backup, doctor, upgrade expectations, and known release limitations.
- Require deterministic tests for changed UI/application helpers where useful, a real release-facing UI smoke test, and a fresh independent read-only M7-H Auditor.
- After qualification, commit locally and create local annotated tag `m7h-qualified`.

M7-I authority:

- M7-I is the release qualification stage and must demonstrate that the first release is installable, upgradeable, recoverable, and operable in realistic conditions.
- Build durable release qualification evidence/checklist covering fresh install; upgrade from qualified M2 state; repeated upgrade/startup; Codex unavailable; live authenticated Codex; network unavailable; scheduled headless run; overlapping manual/scheduled run; application code upgrade; migration failure; backup; and `serve` port conflict.
- Minimum deterministic/packaging gate: full `pytest`, `ruff check .`, strict `mypy` over `src` and `tests`, `python -m compileall -q src tests`, `git diff --check`, Git hygiene/inventory checks, package build/install verification, isolated fresh-venv installation, and installed CLI smoke tests.
- Use real clean environments where practical and document exact environment limitations when a test truly cannot be executed.
- After the qualification matrix passes, launch a fresh independent read-only M7-I Auditor over qualification evidence, code/config/data separation, migration/backup safety, scheduler semantics, CLI behavior, release docs, package metadata, secret/privacy hygiene, upgradeability boundaries, and deferred findings.
- After qualification, commit locally and create local annotated tag `m7i-qualified`.

Release-candidate gate authority:

- Do not begin M3, M5, or M6 and do not perform a public/final release automatically.
- Determine existing package versioning state. If the final release version is not unambiguously established by project history/configuration, recommend a version in the human review packet rather than silently inventing product version policy.
- Prepare release notes, installation instructions, first-run instructions, upgrade instructions from existing development/M2 installations, scheduler instructions, backup/recovery instructions, Codex subscription authentication instructions, optional OpenAI API instructions, known limitations, deferred MINOR/OPTIONAL findings, and post-release roadmap.
- Known intentional release limitations must include arXiv-only source pool, abstract-level analysis rather than full-paper reading, and no M6-style long-term semantic research memory.
- Post-release roadmap: M3 additional websites/source adapters; M5 full-paper/deep reading; M6 persistent research memory.
- Final verification must include full pytest, ruff, strict mypy, compileall, git diff/check/status, secret/runtime-file hygiene, package build/install smoke, installed CLI smoke, data/config/schema version checks, final small live Codex-backed digest, repeated-run/cache behavior, backup validation, doctor, and scheduler/status evidence where available.
- Launch a fresh independent final release Auditor over the complete release delta from `m2-qualified` to the proposed release-candidate commit.
- Resolve BLOCKER/IMPORTANT findings through the campaign repair loop.
- After final Auditor PASS or justified PASS WITH MINOR FINDINGS, ensure a clean worktree, qualified M7-G/M7-H/M7-I commits/tags recorded, release-candidate commit identified, no personal SQLite DB/config/env/auth/cache/agent state tracked, complete release report committed locally, and no final public release/tag/push performed automatically.
- Set this file status to `RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN` with exact RC commit, suggested release version/tag, qualification summary, final audit result, fresh-install evidence, M2-upgrade evidence, live Codex evidence, scheduler evidence, migration/backup evidence, known limitations, deferred findings, and exact proposed release/push commands. Then stop.

Scope boundary:

- This campaign must not implement RSS, Atom/general feeds beyond existing arXiv behavior, arbitrary HTML website extraction, additional source pools, full-paper/PDF deep reading, embeddings/vector memory, long-term semantic trend analysis, or research-question memory.
- Do not introduce Redis, Celery, distributed services, Kubernetes, authentication/multi-user systems, cloud requirements, vector databases, or generic agent frameworks.
- The first release must remain a small, understandable, local-first, upgradeable arXiv research-digest application.

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
- fresh Auditor: PASS with no BLOCKER/IMPORTANT findings. Auditor verified the scheduler boundary is separate from the digest engine, Windows Task Scheduler backend behavior, stable `research-digest run` target, secret exclusion, status visibility, README timezone/DST documentation, deterministic tests, and environment-blocked live Task Scheduler smoke.
- freeze: committed `9d7db2ce0983e8fa1a68534450b890ae110ebed8` (`Qualify M4-B daily scheduling`) and created local annotated tag `m4b-qualified` with tag object `2c204f177d7ace500766365fc49d780ad08d8ceb`.

## M4-C Frozen Specification

Goal: automatic and manual execution cannot corrupt or duplicate work when runs fail, retry, repeat, or overlap.

Run lifecycle:

- Introduce explicit durable lifecycle states using the existing `app_runs` model: `STARTING`, `RUNNING`, `COMPLETED`, `FAILED`, plus `ANALYSIS_UNAVAILABLE` for the existing qualified analyzer-unavailable semantics.
- Preserve readable compatibility for existing M1/M2 rows whose statuses are `running`, `success`, `failed`, or `analysis_unavailable`; normalize them at read boundaries rather than rewriting historical rows unless a migration is required.
- Every new run must have a finite terminal status or be recoverable as stale/crashed.

Exclusion and stale recovery:

- Use SQLite-local locking; do not add Redis, queues, daemons, distributed locks, or external services.
- Scheduled and manual `research-digest run` invocations must not overlap unsafely.
- Use an atomic DB-backed run lock before workflow execution starts.
- If a lock is fresh, a competing invocation exits deterministically with a sanitized error and does not create duplicate work.
- If a lock is stale beyond a finite timeout, mark the stale run failed with a sanitized message and allow a new run.
- Default stale timeout should be conservative and configurable for tests without requiring user decisions.

Persistence and failure semantics:

- Partial provider/source failure must finish the associated run as `FAILED` and keep prior qualified data intact.
- Retry after failure must be supported by releasing/recovering the run lock.
- Repeated unchanged runs must continue to reuse M2 analysis cache semantics.
- Synthesis/calibration must only be computed from a completed per-profile digest result returned by the existing pipeline.
- Errors shown by CLI/UI and stored in DB must remain sanitized.

Scope constraints:

- Do not build a generic workflow engine.
- Do not change scheduler implementation except to rely on the M4-C-safe `research-digest run`.
- Do not redesign M2 article/analysis data or source/analyzer abstractions.
- M4-D will add user-facing History; M4-C only needs enough status data to make failed/running/stale runs durable and inspectable.

Tests required before M4-C freeze:

- simultaneous-run exclusion
- stale/crashed lock recovery
- failed run records terminal failure and sanitized error
- retry after failure succeeds
- repeated unchanged run preserves cache reuse
- database integrity after failed/retry/repeated runs
- existing M2/M4-A/M4-B deterministic tests remain green

Live verification required before M4-C freeze:

- run two headless invocations or service calls against an isolated DB to verify overlap exclusion deterministically
- run a stale-lock recovery smoke against an isolated DB
- if live Codex/network is unavailable, use deterministic fake analyzer/source for lifecycle smoke and record the Codex environment limit separately

## M4-C Candidate Log

- implementation: added SQLite-local `run_locks` table and DB lock acquire/release operations with stale recovery.
- lifecycle: new app runs now start as `STARTING`, move to `RUNNING`, and finish as `COMPLETED`, `FAILED`, or `ANALYSIS_UNAVAILABLE`.
- compatibility: stale recovery recognizes legacy lowercase `running` app rows while preserving existing historical data.
- service boundary: `run_digest_for_profile` and `run_digest_for_enabled_profiles` acquire a shared digest lock; multi-profile headless runs hold one lock for the full batch.
- failure/retry: service locks release in `finally`; failed profile runs remain terminal and sanitized, and later retries can proceed.
- deterministic verification: `pytest` 89 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live lifecycle smoke: isolated overlap exclusion and stale recovery tests passed against temporary SQLite DB.
- initial fresh Auditor: FAIL with two IMPORTANT findings. Stale lock recovery could leave a later-started old run row stuck as `RUNNING`, and `get_app_runs` did not normalize legacy lowercase statuses at the read boundary.
- repair round 1: stale-lock replacement now marks all unfinished `STARTING`/`RUNNING`/legacy `running` rows failed, because the lock itself is the stale/crashed authority. When no lock exists, startup cleanup still only marks unfinished rows older than the stale cutoff. `get_app_runs` now normalizes legacy `running`, `success`, `failed`, and `analysis_unavailable` statuses in its SELECT result. Regression tests cover both auditor probes.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT findings. Re-auditor verified stale-lock replacement, legacy status normalization, service-level lock coverage, explicit lifecycle transitions, sanitized failure, overlap/stale/retry/cache/DB-integrity coverage, and full deterministic gates.
- freeze: committed `2c232fa163c67d8af87e3d039affd11187a5c814` (`Qualify M4-C robust run semantics`) and created local annotated tag `m4c-qualified` with tag object `256cdd6348dc76c05a92dc33d602ee691498ab5c`.

## M4-D Frozen Specification

Goal: automatic operation is inspectable through lightweight digest run history.

History data boundary:

- History must correspond to durable `app_runs` identities.
- Show completed, failed, analysis-unavailable, running, and recovered-failed lifecycle states from the normalized run-status read boundary.
- Historical results must use persisted rows and must not rerun source retrieval, analyzer calls, calibration, or synthesis because current settings changed.
- Do not implement M6 memory: no semantic history search, topic timelines, long-term trend inference, embeddings, or vector store.

Persistence:

- Add the minimal durable storage needed to show a historical run's digest/synthesis where available.
- Store only local user-owned digest summary/synthesis data already produced by a run; no secrets or auth material.
- Prefer storing compact JSON snapshots keyed by `run_id`.
- Failed runs should display sanitized failure details from `app_runs.error_message`.
- Existing historical rows without snapshots must display counts/status and an explicit unavailable-snapshot state rather than mutating or recomputing.

UI:

- Add a Streamlit History view to release navigation.
- Show recent runs in reverse chronological order with date/time, status, profile/source, retrieved/analyzed/relevant counts, and sanitized failure summary when present.
- Selecting a historical run should show its persisted digest/synthesis snapshot where available.
- Use reasonable pagination or a bounded limit.
- Do not duplicate business logic in Streamlit; UI should call a non-UI history/query boundary.

Tests required before M4-D freeze:

- run history list maps normalized durable run statuses and counts
- completed digest run writes an immutable snapshot linked to run id
- failed run displays sanitized error and no fabricated snapshot
- current profile/source setting changes do not mutate historical snapshots
- pagination/limit behavior
- Streamlit History navigation exists
- existing M2/M4-A/M4-B/M4-C deterministic tests remain green

Live verification required before M4-D freeze:

- isolated headless run with fake source/analyzer creates a visible history entry and snapshot
- isolated failed run creates a visible failed history entry with sanitized error

## M4-D Candidate Log

- implementation: added `run_snapshots` table keyed by `run_id`, compact JSON snapshot persistence, and non-UI `research_digest.history` list/detail helpers.
- service boundary: successful per-profile digest runs persist snapshots after valid digest/synthesis creation; failed runs do not fabricate snapshots.
- UI: added Streamlit History navigation/page backed by the history helper module, with bounded run limit, status/count/error display, and persisted snapshot detail.
- immutability: tests verify current profile changes do not mutate prior snapshots.
- deterministic verification: `pytest` 94 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live history smoke: isolated successful and failed history-entry tests passed against temporary SQLite DB.
- fresh Auditor: PASS with no BLOCKER/IMPORTANT findings. Auditor verified durable `app_runs` identity, immutable run snapshots, failed-run handling without fabricated snapshots, unavailable-snapshot display for older rows, History navigation, no M6-style memory/search/timelines, and full deterministic gates.
- freeze: committed `ee280f439b9df3d5478779e33dd55995dabcc9fc` (`Qualify M4-D digest history`) and created local annotated tag `m4d-qualified` with tag object `0ae15c90d886fd9d03c3cf8d3c4f519fc57b5955`.

## M7-A Frozen Specification

Goal: separate replaceable application code from persistent user configuration and SQLite data.

Invariant:

- Code is replaceable.
- User data survives upgrades independently.
- Future code upgrades must not depend on preserving the source checkout.

User directories:

- Use platform-appropriate user directories for config and data.
- A small dependency such as `platformdirs` is allowed if it improves cross-platform correctness.
- Expose the active DB/data location through existing configuration/status surfaces where available.
- Tests must use isolated temporary directories and environment overrides.

Legacy DB adoption:

- Existing repo-local `research_digest.sqlite3` must not be lost.
- On first startup with no user-data DB and a legacy repo-local DB present, safely adopt it by copying to the user data directory.
- Never overwrite one existing DB with another silently.
- If both legacy and user-data DBs exist, prefer the explicit/user-data DB and leave the legacy DB untouched.
- If `RESEARCH_DIGEST_DB` is explicitly set, respect it and do not auto-adopt.

Runtime behavior:

- Default DB path should move from repo-local `research_digest.sqlite3` to user data directory.
- Config directory should be available for future versioned configuration in M7-D.
- Git repo runtime DB remains ignored.
- M4 scheduler must resolve the active DB path deliberately after this change.

Tests required before M7-A freeze:

- default DB path resolves to isolated user data dir under test override
- config dir resolves separately from data dir
- legacy repo-local DB is copied/adopted when no user-data DB exists
- existing user-data DB is never overwritten by legacy adoption
- explicit `RESEARCH_DIGEST_DB` disables adoption and is respected
- scheduler/build config uses the active DB path
- upgrade smoke with a copy of an M2-era DB
- existing M1/M2/M4 deterministic tests remain green

Live verification required before M7-A freeze:

- copy the ignored repo-local DB to a temporary legacy checkout path and verify adoption into a temporary user-data directory without modifying the original
- verify active data location output/path can be inspected without exposing DB contents

## M7-A Candidate Log

- implementation: default DB path now resolves to a platform user data directory using standard-library OS conventions, with a separate config directory resolver.
- compatibility: explicit `RESEARCH_DIGEST_DB` remains authoritative and disables legacy adoption.
- adoption: repo-local or explicitly supplied legacy DB is copied into user data when no user-data DB exists; existing user-data DB is never overwritten.
- provider hygiene: `CodexCLIAnalyzer` no longer calls full app config/DB-path setup just to read Codex model/timeout.
- scheduler: schedule requests use the active config DB path, so scheduled runs target the resolved user-data DB unless explicitly overridden.
- deterministic verification: `pytest` 97 passed; `ruff check .` PASS; strict `mypy --no-incremental src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- live adoption smoke: isolated legacy adoption, no-overwrite, and explicit-override tests passed against temporary DB copies.
- initial fresh Auditor: FAIL with one IMPORTANT finding. Legacy DB adoption copied directly to the final target path, so an interrupted copy could leave a partial DB accepted on the next startup. Auditor also noted MINOR stale M7-A freeze criteria wording and OpenAI provider DB-path side effect.
- repair round 1: legacy adoption now copies to a temporary file, validates SQLite integrity, and atomically replaces the target. Invalid partial active DBs are repaired from a valid legacy DB or fail closed. `OpenAIAnalyzer` no longer calls full app config/DB-path setup when explicit/env API settings are enough.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT findings. Re-auditor verified failure-safe adoption, partial DB repair/fail-closed behavior, explicit DB override, provider no-adoption behavior, scheduler active DB path, ignored runtime state, full deterministic gates, and independent temporary probes.
- freeze: committed `62d6ed4a3902a929d94d6612edc74af0a18cd7a1` (`Qualify M7-A separate user data`) and created local annotated tag `m7a-qualified` with tag object `7a8e3da4ffa79570b5d6748f43a2a586a2268b5e`.

## M7-B Frozen Specification

Goal: introduce explicit versioned SQLite schema migrations and recoverable backups before schema-changing upgrades.

Versioning:

- Persist schema version durably in SQLite.
- Use deterministic ordered migrations with a small stable convention.
- Current post-M7-A schema must become the baseline current version.
- Fresh DB creation, M2-era DB upgrade, and already-current startup must all be deterministic and idempotent.

Migration safety:

- Before any schema-changing upgrade from an older version, create a recoverable SQLite backup.
- Backup path must be visible to callers/tests without exposing DB contents.
- Migrations should run transactionally where SQLite permits.
- Failed migration must not destroy the previous usable DB.
- Interrupted/error paths must fail closed or remain resumable.
- Never test upgrade logic against the user's only live DB; use copies.

Scope:

- Do not introduce a heavyweight migration framework.
- Preserve existing schema behavior unless a migration-safety defect requires a narrow repair.
- M7-G will add user-facing backup/export; M7-B only needs migration safety backup plus stable migration foundation.

Tests required before M7-B freeze:

- fresh DB initializes at current schema version
- current M2-era DB upgrades to current with expected tables/columns preserved
- already-current DB startup is idempotent and creates no duplicate data
- schema-changing migration creates a visible backup
- migration failure leaves previous usable DB recoverable
- interrupted/error path fails closed or resumes safely
- backup restoration/recovery path validates with SQLite integrity check
- existing M1/M2/M4/M7-A deterministic tests remain green

Live verification required before M7-B freeze:

- upgrade smoke using a copy of a qualified M2-era style DB
- backup file opens and passes SQLite integrity check

Freeze criteria:

- fresh independent read-only M7-B audit PASS
- `pytest`, `ruff check .`, `mypy --no-incremental src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m7b-qualified`

Candidate implementation:

- Added `CURRENT_SCHEMA_VERSION` and durable `schema_metadata` storage for the SQLite schema version.
- Replaced startup ad hoc schema setup with a small ordered `SchemaMigration` convention.
- Preserved legacy relevance-analysis and app-run column migrations inside the ordered sequence.
- Added migration backup creation before schema-changing upgrades of existing unversioned/older DBs.
- Exposed `Database.last_migration_backup_path`, `Database.get_schema_version()`, and `Database.get_last_migration_backup_path()`.
- Failed migrations raise `MigrationError` with the recoverable backup path and roll back active DB mutations.

Verification:

- focused DB tests: `pytest tests/test_db.py` passed, 12 tests.
- full test suite: `pytest` passed, 103 tests.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- isolated M2-era style upgrade smoke: PASS; backup file opened and passed SQLite integrity check.

Audit:

- fresh independent read-only M7-B Auditor: PASS with no BLOCKER/IMPORTANT findings.
- auditor MINOR about stale M7-B freeze-criteria wording was repaired before freeze.
- freeze: committed `73b549a75d372ad754f2a90f5c6aae788c7434fa` (`Qualify M7-B database migrations`) and created local annotated tag `m7b-qualified` with tag object `ad09bde4eb4a6103e147e729c4bb0024d6bd19a6`.

## M7-C Frozen Specification

Goal: minimally formalize stable typed extension boundaries so future M3, M5, and M6 campaigns can be additive upgrades, not rewrites.

Boundaries to preserve and formalize:

- source adapters: M3 must be satisfiable by adding source definitions/adapters, not by replacing the digest pipeline.
- analyzers: provider construction must remain a registry/factory boundary, not UI/CLI conditionals.
- preselection: abstract preselection remains a typed service boundary before analysis.
- synthesis: daily synthesis remains replaceable through a typed synthesis boundary.
- future content retrieval: M5 full-paper readers must attach deeper content to normalized articles without replacing `Article` or abstract-level analysis.
- future delivery: delivery/export/notification services must consume digest outputs without owning pipeline logic.
- future memory/history: M6 memory/index services must consume durable digest/run outputs without replacing the current article/digest fundamentals.

Scope:

- Do not implement M3, M5, or M6 features.
- Do not build a dynamic plugin marketplace, generic workflow engine, vector database, queue, or agent framework.
- Prefer protocols, small registries, and explicit configuration.
- Preserve all M2/M4/M7-A/M7-B behavior.

Tests required before M7-C freeze:

- default source registry exposes arXiv and can accept an added source definition.
- default analyzer registry preserves codex/openai behavior and rejects unsupported providers clearly.
- service boundary can accept an alternate synthesis builder without changing pipeline logic.
- typed future content/delivery/memory protocols are importable without adding runtime dependencies.
- full deterministic test suite remains green.

Live verification required before M7-C freeze:

- a temporary source/analyzer/preselector/synthesizer smoke run proves the pipeline can be extended by injection without touching UI/CLI business logic.

Freeze criteria:

- fresh independent read-only M7-C audit PASS
- `pytest`, `ruff check .`, `mypy --strict src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m7c-qualified`

Candidate implementation:

- Added typed source definitions and a source registry with arXiv as the default release source.
- Added `SourceRunRequest` carrying `source_name`, adapter, and source-specific config together.
- Generalized the pipeline/service source execution path to consume `SourceRunRequest[Any]`; the default remains arXiv-first when no request is supplied.
- Added an analyzer registry/factory boundary while preserving codex/openai provider behavior.
- Added a typed cross-paper synthesizer boundary and service injection point while preserving deterministic synthesis as the default.
- Added import-only content, delivery, and memory protocols for future additive M5/M6 work without implementing those campaigns.
- Added architectural regression tests for source/analyzer registries, unsupported analyzer behavior, alternate synthesis injection, and future protocol importability.

Audit:

- initial fresh independent M7-C Auditor: FAIL with one IMPORTANT finding. The source execution path was still arXiv-shaped through service/pipeline/model typing, and the test did not prove a non-arXiv source config could flow through.
- repair round 1: source execution now uses `SourceRunRequest[Any]`; `DigestResult.source_config` is source-generic; the extension smoke passes a `DummySourceConfig` through service/pipeline without casts to arXiv config.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT/MINOR findings. Re-auditor verified generic source adapter/config flow, non-arXiv extension smoke coverage, no M3/M5/M6 feature implementation, and full deterministic gates.
- freeze: committed `246b1fee3a983e5da88e54c8f67850d0a6d3fa4f` (`Qualify M7-C extension boundaries`) and created local annotated tag `m7c-qualified` with tag object `1c8f5c66d3b0b217057f39af53a3e210288db0fd`.

## M7-D Frozen Specification

Goal: persisted configuration must have explicit version semantics while preserving explicit environment overrides.

Configuration file:

- Store a small JSON configuration file in the resolved user config directory.
- Persist a durable `config_version`.
- Version `1` captures the current release semantics for analyzer provider, OpenAI model, Codex model, and Codex timeout.
- Missing config file should initialize defaults without requiring Streamlit.
- Supported older config can be upgraded deterministically with a `.bak` copy.
- Unknown future config versions must fail clearly rather than being silently interpreted.

Overrides:

- Existing environment variables remain explicit overrides:
  `RESEARCH_DIGEST_ANALYZER`, `OPENAI_MODEL`, `RESEARCH_DIGEST_CODEX_MODEL`,
  `RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS`, `OPENAI_API_KEY`, and path overrides.
- Environment overrides must not rewrite the persisted config implicitly.
- Semantic settings such as analyzer provider and provider model/timeout values must not be silently redefined.

Scope:

- Do not introduce an elaborate configuration framework.
- Do not persist secrets or API keys.
- Do not change M2/M4/M7 behavior except adding deterministic config-file defaults/upgrades.

Tests required before M7-D freeze:

- missing config file initializes versioned defaults.
- current versioned config loads deterministically.
- old supported config upgrades to current with backup.
- unknown future config version fails clearly.
- invalid semantic settings fail clearly.
- environment overrides take precedence without mutating the config file.
- config backup/export path is straightforward and contains no secrets.
- full deterministic suite remains green.

Live verification required before M7-D freeze:

- isolated temporary config-directory smoke initializes defaults, applies an env override without file mutation, upgrades an old config copy with backup, and rejects a future version.

Freeze criteria:

- fresh independent read-only M7-D audit PASS
- `pytest`, `ruff check .`, `mypy --strict src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m7d-qualified`

Candidate implementation:

- Added a small versioned JSON config file at the resolved user config directory.
- Added `CONFIG_VERSION = 1`, durable `config_version`, and config path/backup metadata in `AppConfig`.
- Missing config initializes deterministic defaults without Streamlit.
- Version 0 configs upgrade to version 1 with a `.bak-v0-to-v1` copy.
- Unknown future config versions fail clearly.
- Persisted config validates analyzer provider, provider models, Codex timeout, and supported keys.
- Persisted config rejects secret/API-key keys.
- Environment overrides remain explicit and are applied after persisted config load without mutating the file.
- Environment model and timeout overrides are validated and trimmed rather than silently accepting empty/blank values.

Audit:

- initial fresh independent M7-D Auditor: FAIL with one IMPORTANT finding. `OPENAI_MODEL` and `RESEARCH_DIGEST_CODEX_MODEL` env overrides bypassed non-empty semantic validation.
- repair round 1: environment model overrides now use shared non-empty trimmed validation; added regression tests for empty `OPENAI_MODEL` and blank `RESEARCH_DIGEST_CODEX_MODEL`.
- fresh re-Auditor after repair round 1: PASS with no BLOCKER/IMPORTANT/MINOR findings. Re-auditor verified env model override validation, version load/init/upgrade/future-version rejection, backup path visibility, secret-key rejection, regression coverage, and full deterministic gates.
- freeze: committed `2c1f9feb5ca95accf28527b0956727bb275642d0` (`Qualify M7-D versioned configuration`) and created local annotated tag `m7d-qualified` with tag object `e02247e1796fab983d220916f6db73a8c7056ffd`.

## M7-E Frozen Specification

Goal: provide a stable user-facing installed command surface for release operation.

Command surface:

- `research-digest --version`
- `research-digest serve`
- `research-digest run`
- `research-digest status`
- `research-digest schedule ...`
- `research-digest doctor`
- `research-digest backup`

Requirements:

- `serve` launches the Streamlit UI through the supported app entry point, not a development-only incantation.
- `serve` resolves ordinary port conflicts by selecting an available local port and printing the actual usable URL.
- `serve` must not duplicate business logic from the UI or service layer.
- `run` remains the M4 headless execution path.
- `status` reports current data path, provider, schema version, config version, last run, and schedule status if available.
- `status` must not expose secrets.
- `doctor` and `backup` command slots may be stable placeholders in M7-E; M7-F and M7-G will implement their release behavior.
- Schedule subcommands remain available from M4-B.

Tests required before M7-E freeze:

- `--version` reports package version.
- `serve` builds the correct Streamlit invocation and selected URL using mocked subprocess/port probes.
- `serve` skips an occupied port and uses the next available port.
- `run` behavior remains covered by existing CLI tests.
- `status` reports data path, provider, schema/config versions, last run summary, and schedule status without secrets.
- `doctor`/`backup` slots exist and return clear bounded messages until M7-F/M7-G.
- full deterministic suite remains green.

Live verification required before M7-E freeze:

- isolated CLI smoke for `--version`, `status --json`, and mocked `serve` URL selection.

Freeze criteria:

- fresh independent read-only M7-E audit PASS
- `pytest`, `ruff check .`, `mypy --strict src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m7e-qualified`

Candidate implementation:

- Added `research-digest --version`.
- Added `research-digest serve`, launching `python -m streamlit run <installed ui/app.py> --server.headless=true` through the supported Streamlit entry point.
- Added serve port probing with fallback to the next available local port and printed usable URL.
- Added `research-digest status` with text/JSON output for data path, config path, analyzer provider, schema version, config version, last run, and scheduler status.
- Preserved `research-digest run` and `research-digest schedule ...`.
- Added stable `research-digest doctor` and `research-digest backup` command slots with bounded deferred messages for M7-F/M7-G.
- Added CLI tests for version, serve invocation/port fallback, status JSON, and deferred command slots.

Verification:

- focused CLI tests: `pytest tests/test_cli.py tests/test_cli_schedule.py` passed, 11 tests.
- full test suite: `pytest` passed, 120 tests.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- isolated CLI smoke: PASS for `--version`, temp-path `status --json`, and mocked `serve` URL selection.

Audit:

- fresh independent read-only M7-E Auditor: PASS with no BLOCKER/IMPORTANT/MINOR findings. Auditor verified version output, Streamlit serve entry point and port fallback, preserved run path, status output, schedule preservation, deferred doctor/backup slots, CLI test coverage, and deterministic gates.
- freeze: committed `262bdd84be0c634c0b254e325c54304c0e840eb7` (`Qualify M7-E user CLI`) and created local annotated tag `m7e-qualified` with tag object `5e46f46ec355391f7ee479d565855025cfa1db94`.

## M7-F Frozen Specification

Goal: implement `research-digest doctor` as bounded, safe diagnostics.

Checks:

- supported Python/runtime
- user data directory readable/writable
- SQLite DB readable and integrity-valid
- schema version supported
- config version supported
- analyzer provider configuration
- Codex executable available when configured for Codex
- Codex authentication usability only when safely testable without exposing secrets
- arXiv/network reachability only when explicitly requested
- scheduler configuration/status
- last scheduled/headless run health

Requirements:

- no secret output
- finite timeouts
- distinguish WARNING from FAILURE
- useful exit code: `0` for no failures, `1` when any failure exists
- checks individually testable/mocked
- offline/skip-network default; network reachability should require an explicit flag
- do not auto-repair anything
- preserve M7-E CLI shape

Tests required before M7-F freeze:

- doctor JSON/text output covers success, warning, and failure severities.
- missing Codex executable under Codex provider reports FAILURE.
- OpenAI provider without API key reports FAILURE without printing secrets.
- SQLite/schema/config checks pass/fail deterministically with temp paths.
- scheduler status errors are warnings/failures as appropriate and sanitized.
- network check is skipped by default and bounded when requested through mocks.
- full deterministic suite remains green.

Live verification required before M7-F freeze:

- isolated `doctor --json` smoke using temp data/config paths.
- mocked network doctor smoke with finite timeout path.

Freeze criteria:

- fresh independent read-only M7-F audit PASS
- `pytest`, `ruff check .`, `mypy --strict src tests`, `compileall -q src tests`, and `git diff --check` PASS
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state
- commit and annotated local tag `m7f-qualified`

Candidate implementation:

- Added `research_digest.doctor` with typed `DoctorCheck`, `DoctorReport`, and PASS/WARNING/FAILURE severities.
- Implemented checks for Python runtime, data/config directory writability, SQLite integrity, schema version, config version, analyzer provider setup, scheduler status, last run health, and optional arXiv network reachability.
- Wired `research-digest doctor` to text/JSON output, `--network`, and `--network-timeout`.
- Preserved no-auto-repair behavior.
- Kept `research-digest backup` deferred for M7-G.
- Added doctor tests for success/warning/failure, missing Codex, missing OpenAI key, failed last run, scheduler sanitization, network skip/request behavior, and backup deferral.

Verification:

- focused doctor/CLI tests: `pytest tests/test_doctor.py tests/test_cli.py` passed, 14 tests.
- full test suite: `pytest` passed, 127 tests.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- isolated doctor CLI smoke: PASS for temp-path `doctor --json`.
- mocked network doctor smoke: PASS with finite timeout.

Audit and repair:

- fresh independent read-only M7-F Auditor returned FAIL with three IMPORTANT findings: real CLI doctor initialized/migrated state; scheduler status messages were not sanitized; invalid network timeouts such as `inf` were forwarded to the network checker.
- repair round 1 made production doctor inspect config/data/SQLite state read-only, sanitize scheduler status messages, and reject non-finite/non-positive/excessive network timeouts before network execution.
- repair round 1 verification: focused `pytest tests/test_doctor.py tests/test_cli.py` passed, 18 tests; full `pytest` passed, 131 tests; `ruff check .` PASS; strict `mypy --strict src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS.
- read-only smoke: temp-path `doctor --json` did not create data/config directories or SQLite DB.
- fresh independent M7-F repair round 1 re-auditor returned PASS with no BLOCKER/IMPORTANT findings.
- freeze: committed `478f4d8582a2e3c9ad7b114fcfb4301253b1a961` (`Qualify M7-F doctor diagnostics`) and created local annotated tag `m7f-qualified` with tag object `68746dba9d860cb53b3682ccc19d82b087411984`.

## M7-G Frozen Specification

Goal: provide a reliable user-facing backup operation and a simple portable export of user-owned semantic data.

CLI surface:

- Implement `research-digest backup`.
- Default behavior creates a recoverable snapshot of persistent user data using SQLite's backup API.
- Provide `--json` machine-readable output.
- Provide `--export-json` for a portable semantic export when practical.
- If an export path/directory option is needed, keep it explicit and deterministic.

Backup behavior:

- Backup the active configured SQLite database without requiring Streamlit.
- Use a safe SQLite backup strategy rather than raw copy for active DBs.
- Never include `.env`, Codex auth material, API keys, virtualenvs, caches, or local runtime agent state.
- The generated backup path must be printed.
- Missing/uninitialized DB must fail clearly without creating a replacement DB.
- Backup output should be suitable for recovery with documented manual file replacement.

Export behavior:

- Export local user-owned semantic data only:
  profiles, source settings, feedback, digest run summaries, and saved syntheses/snapshots where available.
- Do not export secrets/auth material or private raw local database internals beyond the release data model.
- JSON is required for this release; Markdown remains optional unless trivial.

Tests required before M7-G freeze:

- backup creates a valid SQLite snapshot from an isolated temp DB.
- backup refuses missing or invalid DBs without creating state.
- backup path output is deterministic enough to assert and contains no secrets.
- JSON export contains profiles/source settings/feedback/run summaries/synthesis snapshots where present.
- JSON export excludes API keys, environment values, `.env`, and local runtime paths.
- CLI `backup --json` returns useful success/failure status and exit codes.
- full deterministic suite remains green.

Live verification required before M7-G freeze:

- isolated backup CLI smoke against a temp DB; open the backup and run `PRAGMA integrity_check`.
- isolated JSON export CLI smoke against a temp DB; validate JSON shape and secret exclusion.

Candidate implementation:

- Added `research_digest.backup` with typed backup result and sanitized `BackupError`.
- Implemented `research-digest backup` with `--json`, `--output`, and `--export-json`.
- Backup uses SQLite's backup API from a read-only source connection and validates the backup with `PRAGMA integrity_check`.
- Backup refuses missing, non-file, invalid, or unsupported-schema databases before creating output directories.
- Default backup destination is the active DB data directory's `backups/` folder; explicit file or directory output is supported without overwriting existing explicit files.
- JSON export writes a sidecar `.export.json` file containing export version, schema version, profiles, source settings, feedback, app run summaries, and run snapshots.
- Export sanitizes persisted run error messages and does not read or emit environment secrets, `.env`, Codex auth material, virtualenvs, caches, or local runtime agent state.
- Removed the M7-E/M7-F deferred backup behavior.

Verification:

- focused `pytest tests/test_backup.py tests/test_cli.py`: 12 passed.
- focused `ruff check src/research_digest/backup.py src/research_digest/cli.py tests/test_backup.py tests/test_cli.py`: PASS.
- focused strict `mypy --strict src/research_digest/backup.py src/research_digest/cli.py tests/test_backup.py tests/test_cli.py`: PASS.
- full `pytest`: 135 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- isolated CLI smoke: real `python -m research_digest.cli backup --json --output <tmp>/backups --export-json` against a temp DB returned exit 0; generated backup opened with SQLite `integrity_check=ok`; JSON export contained one profile and one run.

Interruption recovery:

- recovery performed after authentication renewal found local HEAD at `478f4d8582a2e3c9ad7b114fcfb4301253b1a961` with tag `m7f-qualified`; no `m7g-qualified` tag or M7-G commit exists.
- M7-G candidate changes are present only as unstaged/uncommitted worktree files: `src/research_digest/backup.py`, `src/research_digest/cli.py`, `tests/test_backup.py`, `tests/test_cli.py`, `tests/test_doctor.py`, and campaign docs.
- no staged diff exists.
- durable campaign docs recorded that a fresh M7-G Auditor had been requested, but did not record the interrupted Auditor's IMPORTANT finding.
- reconstructed outstanding IMPORTANT finding: backup opens read-only SQLite databases with an unsafe raw `file:{path}?mode=ro` URI, so paths containing SQLite URI-reserved characters such as `?` or `#` may be misinterpreted.
- Worker self-review also reconstructed one required backup hardening repair: when `--export-json` is requested and the derived JSON sidecar already exists, backup must fail before writing the SQLite backup instead of leaving a new backup after export failure.

Repair round 1:

- `_read_only_connection` now builds the SQLite read-only URI from `Path.as_uri()` so path characters are escaped before appending `mode=ro`.
- `run_backup` now resolves and checks the derived JSON export sidecar before writing the SQLite backup when `--export-json` is requested.
- regression tests cover DB filenames containing SQLite URI-reserved characters and pre-existing export sidecars.

Repair round 1 verification:

- focused `pytest tests/test_backup.py tests/test_cli.py`: 14 passed.
- focused `ruff check src/research_digest/backup.py tests/test_backup.py`: PASS.
- focused strict `mypy --strict src/research_digest/backup.py tests/test_backup.py`: PASS.
- full `pytest`: 137 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- isolated CLI smoke against temp DB path `db?with#reserved.sqlite3`: exit 0; backup SQLite `PRAGMA integrity_check=ok`; JSON export contained one profile.

Fresh closure audit:

- fresh independent read-only M7-G repair round 1 closure Auditor returned PASS with no BLOCKER/IMPORTANT/MINOR findings.
- Auditor verification: `pytest tests/test_backup.py tests/test_cli.py tests/test_doctor.py` 24 passed; full `pytest` 137 passed; `ruff check .` PASS; strict `mypy --strict src tests` PASS; `compileall -q src tests` PASS; `git diff --check` PASS; isolated CLI smoke with `db?with#reserved.sqlite3` PASS; existing sidecar failed before backup creation.

Post-audit qualification:

- full `pytest`: 137 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Freeze:

- committed `e972d95933fc8145924883f0fa29cfeec52d4600` (`Qualify M7-H release UI polish`) and created local annotated tag `m7h-qualified` with tag object `4a1b6ab618265a15f9c99682e4d638583f362c32`.

## M7-I Frozen Specification

Goal: demonstrate that the first release is installable, upgradeable, recoverable, and operable in realistic conditions.

M7-I is a release qualification stage, not a feature-development stage.

Required qualification matrix:

- Case 1 fresh install: isolated fresh environment, no existing DB/config; package installs, CLI exists, data/config directories initialize correctly, fresh DB/schema/config initialize, enough state can be configured for a digest, and the application starts cleanly. Do not depend on the development checkout remaining on `PYTHONPATH`.
- Case 2 upgrade from qualified M2 state: use a copy of representative M2-era data, never the user's only live DB; verify adoption/migration preserves profiles, source settings, articles, relevance analyses, preselection data, feedback/calibration, synthesis/digests, and run history where applicable; validate counts and meaningful relationships/invariants.
- Case 3 repeated upgrade/startup: repeated startup after upgrade must not duplicate migrations, duplicate semantic data, recreate/adopt legacy state incorrectly, or corrupt configuration.
- Case 4 Codex unavailable: with Codex provider configured but executable/auth unavailable, doctor/status/run give clear bounded failure/warning, no secrets are exposed, DB remains valid, and UI remains reasonably inspectable.
- Case 5 live Codex authenticated: perform a small real subscription-backed Codex digest covering arXiv, preselection, relevance analysis, feedback/calibration context as applicable, synthesis, persistence, and history.
- Case 6 network unavailable: simulate or exercise bounded network failure, sanitized failure, failed run record, DB integrity preservation, and later retry.
- Case 7 scheduled headless run: exercise supported scheduling path on current WSL2/Windows where available; verify stable installed CLI, no Streamlit dependency, History/status visibility, inspectable schedule status, and no secrets embedded in task command line.
- Case 8 overlapping manual/scheduled run: verify M4-C exclusion behavior, safe duplicate/racing prevention, user-visible/CLI outcome, no corruption, and stale lock recovery.
- Case 9 application code upgrade: verify code is replaceable and user data/config survive replacement/reinstallation/upgrading of application code.
- Case 10 migration failure: controlled disposable migration failure verifies pre-migration backup where required, recoverability of previous user data, fail-closed behavior, and documented/testable recovery procedure.
- Case 11 backup: verify `research-digest backup`, SQLite snapshot validation, JSON export validation, awkward/reserved source paths, collision behavior, and secret exclusion.
- Case 12 serve/port conflict: verify `research-digest serve` handles an unavailable preferred port sensibly, prints actual usable URL, avoids raw Streamlit development invocation, and remains bounded/understandable.

Minimum deterministic/packaging gate:

- full `pytest`
- `ruff check .`
- strict `mypy --strict src tests`
- `python -m compileall -q src tests`
- `git diff --check`
- Git hygiene/inventory checks
- package build/install verification
- isolated fresh-venv installation
- installed CLI smoke tests

Execution rules:

- Use real clean environments where practical.
- Do not depend only on the current development venv.
- Document exact environment limitations when a case cannot be executed.
- After the qualification matrix passes, launch a fresh independent read-only M7-I Auditor.

Freeze criteria:

- fresh independent read-only M7-I audit PASS or justified PASS WITH MINOR FINDINGS.
- all required deterministic/packaging gates PASS or have documented environment limitations where live execution is impossible.
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state.
- commit and annotated local tag `m7i-qualified`.

Candidate implementation/evidence:

- Added durable matrix document `docs/campaigns/release1/M7I_QUALIFICATION_MATRIX.md` covering all twelve restored-charter release qualification cases.
- Added deterministic release qualification harness `tests/test_release_qualification_matrix.py`.
- Harness covers fresh install-like config/DB/status initialization, representative unversioned/M2-style data adoption and migration, repeated startup without duplicate semantic data, backup/export from upgraded data, Codex-unavailable doctor behavior without secrets, sanitized bounded network failure, and serve port-conflict command construction.
- Package build and fresh-venv install were attempted and are environment-blocked by inability to resolve `hatchling` from PyPI, including after network escalation.
- Live arXiv reachability is environment-blocked by DNS failure, including after network escalation.
- Live Codex execution is environment-blocked: default Codex home hits read-only filesystem; throwaway writable `CODEX_HOME` reaches CLI session setup but cannot connect to OpenAI endpoints from this environment.
- Live Windows Task Scheduler path remains environment-blocked by WSL `UtilBindVsockAnyPort ... socket failed 1`.
- Live `research-digest serve` listener remains environment-blocked by local socket `Operation not permitted`; deterministic port-conflict command construction remains covered.

Candidate verification:

- `pytest tests/test_release_qualification_matrix.py`: 4 passed.
- `ruff check tests/test_release_qualification_matrix.py`: PASS.
- strict `mypy --strict tests/test_release_qualification_matrix.py`: PASS.
- `python -m pip show research-digest`: PASS in current venv, editable install version `0.1.0`.
- temp-path `python -m research_digest.cli status --json`: PASS.
- `python -m research_digest.cli doctor --json`: PASS with sanitized environment warnings and no failures.
- `python -m research_digest.cli --version`: PASS, `research-digest 0.1.0`.

Full candidate gate:

- full `pytest`: 143 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Initial M7-I audit:

- fresh independent read-only M7-I Auditor returned FAIL with two BLOCKER findings.
- BLOCKER 1: installed CLI smoke evidence was missing and contradicted by the environment; the candidate used `python -m research_digest.cli`, while `research-digest` was not on PATH and the editable install did not expose a console script.
- BLOCKER 2: the upgrade harness did not durably demonstrate upgrade from qualified M2 state; it created current-schema data with the current `Database` API, dropped only `schema_metadata`, and included current run snapshots.

Repair round 1:

- Replaced the external `hatchling` build backend with repo-local `_research_digest_build`, a minimal pure-Python PEP 517 backend that builds the package wheel and declared `research-digest` console script without network access.
- Replaced the upgrade fixture with hand-built representative `m2-qualified` schema/data: no `schema_metadata`, no run snapshots, M2-style profiles/source settings/articles/relevance analyses/profile fingerprints/feedback/app run/preselection counters.
- The repair harness verifies schema migration to current version, pre-migration backup creation, semantic count stability across repeated startup, M2 fingerprint preservation, and backup/export from the upgraded copy.

Repair round 1 focused verification:

- `pytest tests/test_release_qualification_matrix.py`: 5 passed.
- `ruff check _research_digest_build.py tests/test_release_qualification_matrix.py pyproject.toml`: PASS.
- strict `mypy --strict tests/test_release_qualification_matrix.py`: PASS.
- `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-package.CtC0I9/wheelhouse`: PASS.
- isolated fresh-venv wheel install with `--no-deps`: PASS.
- installed wheel CLI `/tmp/research-digest-m7i-package.CtC0I9/venv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- installed entry point metadata query: PASS, `research_digest.cli:main`.
- installed wheel CLI `status --json` from `/tmp` with isolated data/config: PASS, schema version 4 and config version 1 initialized; scheduler warning sanitized.
- isolated fresh source install `pip install --no-deps .`: PASS.
- installed source CLI `/tmp/research-digest-m7i-package.CtC0I9/sourcevenv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.

Repair round 1 full gate:

- full `pytest`: 144 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- package backend bytecode/cache repair: `_research_digest_build` now excludes `__pycache__` and `.pyc` files; harness asserts this.
- final current-state `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-finalpkg2.VfZt6V/wheelhouse`: PASS.
- final isolated fresh-venv wheel install with `--no-deps`: PASS.
- final installed CLI `/tmp/research-digest-m7i-finalpkg2.VfZt6V/venv/bin/research-digest --version`: PASS, `research-digest 0.1.0`.
- final installed CLI `status --json` from `/tmp` with isolated data/config: PASS, schema version 4 and config version 1 initialized; scheduler warning sanitized.
- final installed entry point metadata query: PASS, `research_digest.cli:main`.
- final wheel-content cache/bytecode check: PASS, no `__pycache__` or `.pyc` members.

Repair round 1 closure audit:

- fresh independent read-only M7-I Auditor returned FAIL after verifying the two earlier BLOCKERs were closed.
- IMPORTANT finding: the repo-local PEP 517 backend did not support the README-documented editable/dev installation path `pip install -e ".[dev]"`, and package metadata omitted the `dev` extra.

Repair round 1 installability follow-up:

- Added PEP 660 editable hooks to `_research_digest_build`.
- Added `Provides-Extra` and extra-scoped `Requires-Dist` metadata for optional dependencies, including `dev`.
- Added regression coverage for wheel metadata, bytecode/cache exclusion, and the documented editable install command.
- focused `pytest tests/test_release_qualification_matrix.py`: 6 passed.
- focused `ruff check _research_digest_build.py tests/test_release_qualification_matrix.py pyproject.toml`: PASS.
- focused strict `mypy --strict tests/test_release_qualification_matrix.py`: PASS.
- second full `pytest`: 145 passed.
- second full `ruff check .`: PASS.
- second full strict `mypy --strict src tests`: PASS.
- second `python -m compileall -q src tests`: PASS.
- second `git diff --check`: PASS.
- final current-state `python -m pip wheel . --no-deps -w /tmp/research-digest-m7i-finalpkg3.RhYfM6/wheelhouse`: PASS.
- wheel metadata/content check: PASS, no generated bytecode/cache files; console script entry point present; `dev` extra metadata present.
- isolated wheel install with `--no-deps`: PASS.
- installed wheel CLI `--version`: PASS, `research-digest 0.1.0`.
- installed wheel CLI `status --json` from `/tmp` with isolated data/config: PASS.
- documented editable install `pip install -e '.[dev]' --no-deps`: PASS.
- editable installed CLI `--version`: PASS, `research-digest 0.1.0`.

Second closure audit:

- fresh independent read-only M7-I Auditor returned PASS with no BLOCKER/IMPORTANT/MINOR/OPTIONAL findings.
- Auditor independently verified the original installed-CLI and M2-upgrade BLOCKERs remain closed.
- Auditor independently verified the README-documented editable/dev install path is supported, `dev` extra metadata is emitted, wheel/editable installs work from isolated `/tmp` contexts, the twelve-case matrix is credible, generated cache/bytecode files are excluded from wheels, and the environment-blocked live Codex/arXiv/scheduler/serve limitations are concrete and acceptable for M7-I if carried into final RC materials.

Post-audit M7-I qualification:

- full `pytest`: 145 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- staged inventory contained only M7-I docs, the release qualification matrix, packaging metadata/backend, and M7-I harness.
- committed `efc4c88a689d06dc0e4b4428605c05836ddb7374` (`Qualify M7-I release matrix`) and created local annotated tag `m7i-qualified` with tag object `ec016b565fe84857b8053c51822290025b50c0db`.

## Release-Candidate Gate Evidence

Versioning:

- package version in `pyproject.toml`: `0.1.0`.
- runtime version in `src/research_digest/__init__.py`: `0.1.0`.
- no existing public-style `v*` tags found.
- suggested human-reviewed final public tag: `v0.1.0`.

Prepared materials:

- `docs/campaigns/release1/RELEASE_CANDIDATE_PACKET.md`
- `docs/campaigns/release1/FINAL_RELEASE_CANDIDATE_VERIFICATION.md`

Final deterministic verification:

- full `pytest`: 145 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- targeted recovery/cache/migration/backup tests: 51 passed.

Final package/install verification:

- offline wheel build: PASS.
- wheel content/metadata/entry point checks: PASS, including no generated bytecode/cache files and `dev` extra metadata.
- isolated wheel install with `--no-deps`: PASS.
- isolated editable install `pip install -e '.[dev]' --no-deps`: PASS.
- installed wheel CLI `--version`, `status --json`, `doctor --json`, and `backup --json --export-json`: PASS where not dependent on blocked external runtime.

Final live/runtime verification:

- installed live digest with one disposable profile and arXiv max results `1`: environment-blocked by arXiv DNS failure; same result after escalation; failure recorded in run history and DB remains valid.
- Codex CLI exists and reports `codex-cli 0.147.0`; minimal Codex model probe with writable `CODEX_HOME` is environment-blocked by OpenAI websocket/HTTPS transport errors; same result after escalation.
- scheduler status is environment-blocked by WSL Task Scheduler socket error.
- serve listener is environment-blocked by local socket `Operation not permitted`; same result after escalation.
- backup validation: generated SQLite backup has `PRAGMA integrity_check` `ok`; JSON export validates and contains no secrets.

Final audit:

- fresh independent final release Auditor over `m2-qualified..f8d87eda5048c111d5d754c2e089ef3a33254508`: PASS WITH MINOR FINDINGS.
- MINOR: release bookkeeping pointed at M7-I base rather than actual RC commit; corrected in closeout docs.
- MINOR: upgrade/backup instructions needed clearer sequence for older repo-local M2 databases; corrected in README and human packet.

Final release-candidate closeout:

- prior exact RC commit before the live scheduler defect was found: `eadedb71b7a64302edb6ac6b7d1fbfe1d6bfbe95`.
- that prior candidate is superseded by the committed scheduler environment repair; the next exact release-candidate commit remains pending human live scheduler smoke.
- scheduler environment repair commit awaiting human live smoke: `6570aa37dc7c055828977cd490063fb160d08445`.
- suggested release version/tag: `0.1.0` / `v0.1.0`.
- qualification summary: M4-A through M4-D and M7-A through M7-I are locally qualified and tagged; M3, M5, and M6 were not started.
- final audit result: PASS WITH MINOR FINDINGS; both MINOR findings repaired before final human stop.
- fresh-install evidence: package wheel and editable installs pass in isolated venvs; installed CLI `status --json` initializes schema 4/config 1 under isolated data/config paths.
- M2-upgrade evidence: M7-I representative M2-qualified SQL fixture verifies adoption/migration, pre-migration backup, semantic counts, fingerprint preservation, repeated startup, and backup/export.
- live Codex evidence: Codex CLI exists and reports `codex-cli 0.147.0`, but final model probe is environment-blocked by OpenAI websocket/HTTPS transport errors even after escalation.
- scheduler evidence before live human smoke: deterministic scheduler tests pass; automated WSL Task Scheduler status was environment-blocked by `UtilBindVsockAnyPort ... socket failed 1`; later human live scheduler smoke found the Codex PATH defect recorded below.
- migration/backup evidence: deterministic migration failure/recovery tests pass; final installed backup/export smoke passes with SQLite integrity `ok` and valid JSON export.
- known limitations: arXiv-only source pool; abstract-level analysis; no M6 long-term semantic memory; local single-user app; WSL2/Windows scheduler backend; live arXiv/Codex/scheduler/serve probes environment-blocked in this session.
- deferred MINOR/OPTIONAL findings: none.
- exact proposed human release commands:

```bash
git status
git log --oneline --decorate -n 8
git tag -a v0.1.0 -m "Research Digest 0.1.0"
git push origin master
git push origin m7g-qualified m7h-qualified m7i-qualified v0.1.0
```

No final public release tag, remote push, GitHub release, package publication, or public release operation was performed by the campaign.

## Release-Candidate Scheduler Environment Repair

Live finding:

- Interactive WSL has Codex at `/home/inaeyk/.nvm/versions/node/v22.22.2/bin/codex` and `codex login status` reports ChatGPT login.
- Manual installed-CLI run immediately before scheduled smoke completed with subscription-backed Codex on new papers.
- Windows Task Scheduler launched WSL with a non-login environment whose `PATH` did not include the NVM directory containing Codex.
- Scheduled-like `command -v codex` returned no result and `codex login status` failed with `codex: not found`.
- Real scheduled smoke produced run `#25` as `ANALYSIS_UNAVAILABLE` with retrieved/analyzed article counts, and Task Scheduler reported `LastTaskResult: 1`.

Required repair:

- When installing a Codex-backed schedule, resolve the interactive `codex` executable with `shutil.which("codex")`.
- Add the resolved Codex executable directory to the scheduled WSL `PATH` ahead of the normal minimal/system PATH.
- Preserve `HOME` by not overriding it, so Codex can use normal saved ChatGPT authentication.
- Do not embed API keys, OAuth/access/refresh tokens, Codex auth files, or copied auth material in the task action.
- Do not source arbitrary shell startup files or build a general shell-environment manager.
- Missing Codex at schedule-install time must fail clearly for Codex analyzer schedules.
- Reinstalling/updating the schedule should refresh the resolved Codex runtime path after Node/Codex upgrades.

Candidate repair:

- `research_digest.scheduler` now resolves `codex` during Codex-backed schedule installation and adds the resolved executable directory to scheduled `PATH` before `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`.
- The task action continues to pass only non-secret runtime settings and does not override `HOME`.
- OpenAI-provider schedule installation does not require Codex discovery.
- `research-digest doctor` now warns if an installed Codex-backed scheduled action lacks the current resolved Codex directory, indicating the schedule should be reinstalled to refresh a stale Node/Codex runtime path.
- README, release-candidate packet, final verification record, release report, and `RC_SCHEDULER_LIVE_SMOKE.md` document the live finding, repair, and human verification sequence.

Repair verification:

- full `pytest`: 149 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.

Closure audit:

- Fresh independent read-only scheduler repair Auditor: PASS.
- No BLOCKER or IMPORTANT findings.
- Auditor verified Codex-backed schedule install resolves `codex`, scheduled WSL `PATH` contains the resolved Codex executable directory, the task action does not override `HOME` or embed auth/API material, stale scheduler PATH is diagnosable through doctor, deterministic tests cover the repair risks, and human live-smoke instructions are durable.

Human live-smoke gate:

- Required before final release-candidate acceptance.
- Scheduler repair commit under test: `6570aa37dc7c055828977cd490063fb160d08445`.
- Follow `docs/campaigns/release1/RC_SCHEDULER_LIVE_SMOKE.md` to reinstall/update the task, inspect the generated action, trigger the task, verify `LastTaskResult == 0`, verify a new run is `COMPLETED` rather than `ANALYSIS_UNAVAILABLE`, and verify no secrets appear in the task action.

Historical M7-G freeze record:

- committed `4070cce4744fc0862e418b1db51f43019fb0a78c` (`Qualify M7-G backup export`) and created local annotated tag `m7g-qualified` with tag object `1a11880d39ba71aed06163620142eeca0aaa372f`.

## M7-H Frozen Specification

Goal: turn the already-qualified application into a coherent first-release user experience without adding M3/M5/M6 functionality.

Release UI:

- Keep the Streamlit UI modest and local-first.
- Desired release navigation is approximately Today, History, Interests, Sources, Settings.
- Settings may expose existing release functionality such as analyzer/provider selection/status, preselection fraction, schedule status/configuration, active data location, application version, schema/config version, and health/doctor summary.
- Do not duplicate CLI/business logic in Streamlit. Use the same application/service/configuration boundaries already qualified elsewhere.

Required release states:

- First run: useful empty state and clear path to configure an interest profile/source/provider; no traceback when no historical data exists.
- Empty digest: clearly communicate that no eligible/relevant items were found.
- Loading/running: clear visible progress/state; avoid appearing to do nothing.
- No provider/Codex unavailable: sanitized actionable message while keeping the application inspectable where possible.
- Failed run: visible through existing run/history semantics with sanitized error text and no secret/path leakage.
- Stale result: retain M1/M2 semantic invalidation protections.
- History: remain lightweight run history, not M6 semantic memory/trend analysis.
- Sources: remain arXiv-first; do not add RSS, HTML, arbitrary APIs, or other M3 sources.

Installation/user experience:

- Update README and release-facing documentation so ordinary users use installed commands rather than development commands.
- `research-digest serve` is the supported UI launch path.
- Document installation, first run, ChatGPT/Codex CLI authentication, optional OpenAI API provider, data/config locations, manual digest, UI launch, daily schedule install/status/remove, backup, doctor, upgrade expectations, known limitations, and release scope.
- Do not introduce authentication/multi-user support, cloud deployment requirements, fancy frontend frameworks, or M3/M5/M6 functionality.

Tests required before M7-H freeze:

- deterministic tests for changed UI/application helpers where useful.
- UI navigation includes Settings and preserves existing Today/History/Interests/Sources navigation.
- release docs prefer installed CLI (`research-digest serve`) over raw Streamlit development launch.
- first-run/empty/failure state helpers are deterministic and sanitized where changed.
- full deterministic suite remains green.

Live verification required before M7-H freeze:

- real release-facing UI smoke through `research-digest serve` or the same serve command construction path, including port-conflict behavior where practical.

Freeze criteria:

- fresh independent read-only M7-H audit PASS or justified PASS WITH MINOR FINDINGS.
- `pytest`, `ruff check .`, strict `mypy --strict src tests`, `compileall -q src tests`, and `git diff --check` PASS.
- staged inventory excludes `research_digest.sqlite3`, `.venv`, `.env`/secrets, caches, and local agent/runtime state.
- commit and annotated local tag `m7h-qualified`.

Candidate implementation:

- Added a Settings page to Streamlit navigation with release runtime summary, data/config paths, analyzer provider status, doctor health summary, detailed doctor checks, and installed release commands.
- Added Material Symbols icons to the Today, History, Interests, Sources, and Settings navigation entries.
- Improved Today first-run, provider-unavailable, and digest-failure messages with sanitized actionable copy and release CLI guidance.
- Rewrote README around installed release commands: `research-digest serve`, `run`, `status`, `doctor`, `backup`, and schedule install/status/remove.
- README now documents installation, first run, Codex/ChatGPT authentication, optional OpenAI API provider, data/config locations, manual digest, UI launch, scheduling, doctor, backup/recovery, upgrade expectations, known release limitations, and post-release M3/M5/M6 roadmap.
- Added deterministic tests for Settings helper behavior and release README command/limitation coverage.

Candidate verification:

- focused `pytest tests/test_ui_navigation.py tests/test_settings_page.py tests/test_release_docs.py tests/test_today_state.py`: 14 passed.
- focused `ruff check src/research_digest/ui tests/test_ui_navigation.py tests/test_settings_page.py tests/test_release_docs.py`: PASS.
- focused strict `mypy --strict src/research_digest/ui tests/test_ui_navigation.py tests/test_settings_page.py tests/test_release_docs.py`: PASS.
- full `pytest`: 139 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- `python -m research_digest.cli --version`: PASS, `research-digest 0.1.0`.
- temp-path `python -m research_digest.cli status --json`: PASS.
- `python -m research_digest.cli doctor --json`: PASS with sanitized warnings and no failures.
- direct `python -m research_digest.cli serve --port 18601`: blocked by this execution environment with sanitized `[Errno 1] Operation not permitted` during local socket probing; rerun after sandbox escalation had the same socket restriction. Existing deterministic CLI test verifies occupied-port fallback and printed usable URL through the serve command construction path.

Fresh audit:

- fresh independent read-only M7-H Auditor returned PASS with no BLOCKER/IMPORTANT/MINOR findings.
- Auditor verified navigation, required release UI states, Settings reuse of existing config/database/doctor boundaries, release CLI README guidance, known limitations, absence of M3/M5/M6 functionality, Streamlit release concerns, deterministic gates, environment-limited serve smoke documentation, and Git hygiene.

Post-audit qualification:

- full `pytest`: 139 passed.
- `ruff check .`: PASS.
- strict `mypy --strict src tests`: PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
