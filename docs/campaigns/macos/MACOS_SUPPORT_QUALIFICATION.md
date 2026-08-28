# macOS Support Qualification Record

State date: 2026-08-27.

Baseline: `813d380cb73e8de7806dddbb21a83fe5707066ab` ("Freeze qualified Windows
launcher").

The later published-tag clean-install acceptance, with the exact macOS version,
architecture, release identity, and final install evidence, is recorded in
[`V0.4.0_CLEAN_INSTALL_SMOKE.md`](V0.4.0_CLEAN_INSTALL_SMOKE.md).

## Scope and architecture

- The scientific application, SQLite data model, Streamlit pages, detached
  digest workers, cancellation service, and CLI remain shared.
- A narrow platform runtime owns process inspection and browser opening.
  Linux/WSL retains `/proc` identity and the PowerShell Windows browser bridge;
  Darwin uses native `libproc` process start time, `kern.boottime`, POSIX process
  groups, and `/usr/bin/open`.
- Launcher installation is platform-dispatched. Windows retains the qualified
  owned Desktop `.lnk`; macOS installs an owned user-local
  `~/Applications/Research Digest.app` bundle.
- Scheduling remains behind the existing scheduler protocol. Windows retains
  Task Scheduler; macOS uses an owned per-user launchd LaunchAgent.

Package/runtime remains `0.3.0`, SQLite schema remains `18`, JSON config remains
`5`, and UI registration remains version `1`. Registration v1 gains an optional
platform discriminator while old WSL registration files remain readable. No
database or config migration is required.

## Pre-change platform dependency audit

- `ui_server.py`, `background.py`, `ui/run_status.py`, `cancellation.py`, and
  `run_locks.py` directly consumed Linux `/proc` process start/state/boot facts.
- `ui_server.py` always used the PowerShell browser bridge; the detached POSIX
  `start_new_session`/signal mechanics themselves were already Darwin-capable.
- `windows_launcher.py` correctly isolated WSL distribution discovery,
  `wsl.exe` quoting, `.lnk` ownership, and PowerShell and remains the Windows
  implementation.
- `scheduler.py` exposed a backend protocol but selected only Windows Task
  Scheduler and built only WSL requests.
- provider subprocesses already used exact run-scoped database registration,
  POSIX process groups, SIGTERM, and bounded SIGKILL; only their process-start
  reader was Linux-specific.
- Codex providers resolve `codex` from inherited PATH, so a Finder-specific
  scientific implementation was unnecessary; the GUI launcher only needs a
  deterministic non-interactive PATH.
- `config.py` already selected native macOS Application Support paths. No data
  relocation or schema migration was warranted.

## macOS launcher and Codex boundary

The generated app contains a deterministic `Info.plist`, a minimal executable
shim, and an ownership marker. The shim invokes the exact installed
`research-digest launch` entry point, carries only non-secret data/config paths,
and exits after the canonical launch command returns. It does not contain user
credentials, API keys, database content, or Codex authentication.

Finder does not load interactive shell profiles. Launcher installation therefore
optionally resolves the actual Codex executable available in the installation
Terminal (and requires it when Codex is the primary analyzer) and
captures its parent directory plus the directory of a validated interpreter
declared through an `/usr/bin/env` shebang (for example `node`) in the app PATH.
Users rerun
`research-digest install-launcher` if the Research Digest or Codex installation
moves. Codex authentication remains in Codex's own user configuration. A
deterministic test executes an env-shebang Codex shim with interactive PATH
state removed.

## Real-Mac launcher identity repair

The first native smoke proved that Streamlit started, owned a new process group,
and returned HTTP 200 from `/_stcore/health`, but Darwin `ps` reported the
underlying framework `Python.app` executable rather than the virtual-environment
Python symlink recorded at launch. The original command corroboration therefore
rejected the exact process and eventually emitted a misleading reachability
timeout.

Darwin corroboration now keeps PID, native microsecond start identity, boot
identity, application registration, exact app path, exact bind address/port,
and recorded process group authoritative. It accepts an architecture-neutral
Python executable of any normal Python 3 form, while comparing every
application-owned `-m streamlit run` argument exactly. Linux/WSL retains its
`/proc` nonce and executable behavior. Startup separately diagnoses process
exit, identity-validation failure, and identity-valid health failure.

The supported source-checkout setup now includes `scripts/bootstrap_macos.sh`.
It verifies Python 3.11 or newer before creating `.venv`, can discover common
versioned Python 3 executables, and gives a concise python.org/Homebrew or
`RESEARCH_DIGEST_PYTHON` remedy without creating an unsupported environment.

## launchd boundary

The macOS backend owns only
`~/Library/LaunchAgents/org.research-digest.daily.plist`. It uses the exact
Research Digest executable, a local calendar interval, the existing headless
`run` command, non-secret configuration paths, and, when Codex is installed, a
captured Codex executable and validated shebang-interpreter path. Install/update
is idempotent and rollback-safe; remove refuses an unowned artifact. Cancelling
a running digest does not alter this LaunchAgent.

## Path policy

Existing platform path policy is retained. Native macOS config, SQLite data,
UI registration/logs, scheduler logs, and backups live below
`~/Library/Application Support/Research Digest`; launcher state does not live in
the app bundle or repository. Windows/WSL paths are unchanged.

## Acceptance state

Real-macOS human acceptance passed on 2026-08-27. The exact Mac model,
architecture, and macOS version were not included in the acceptance record and
remain unavailable rather than inferred from installation paths. The human
verified:

- `install-launcher` created the owned user-local
  `~/Applications/Research Digest.app`, Finder opened the default browser, and
  no Terminal remained open;
- repeated Finder launches reused one UI server, native Darwin ownership
  validation accepted the exact framework-Python Streamlit process, fallback
  ports worked, and an unrelated listener was not disturbed;
- a Finder-launched real digest completed retrieval, model-backed Stage 1, and
  full Codex analysis, proving the noninteractive executable and authentication
  boundary;
- closing/stopping/reopening the UI did not stop the detached digest and the
  replacement UI reattached with durable progress and cancellation available;
- native provider cancellation reached `CANCELLED`, released the run lock
  promptly, preserved partial analysis, preserved complete source coverage,
  and allowed an immediate later run;
- launchd install, status, and invocation worked, and cancelling a scheduled
  run did not disable its schedule.

The observed cancellation sample retrieved and stored 23 papers, preselected
9, skipped full analysis for 14, persisted 5 completed analyses, recorded
complete retrieval and source coverage for `2026-08-26`, then terminalized as
`CANCELLED` with a user cancellation reason, completion/cancellation timestamps,
and no remaining run lock.

Native macOS also exposed a portable test-fixture difference: temporary paths
under `/var/folders` canonicalize to `/private/var/folders`. The UI-server log
assertion now uses the same `Path.resolve()` policy as `UIServerManager`; no
production path behavior changed.

Final deterministic qualification from WSL/Linux:

- Full suite after the native launcher repair: 541 passed, one native-Darwin
  test skipped, and 9 subtests passed.
- Explicit Streamlit AppTest suites: 64 passed.
- Final macOS platform slice: 73 passed and one native-Darwin test skipped.
- Final Windows/WSL launcher regression slice: 47 passed.
- Final cancellation, process-ownership, and scheduler slice: 76 passed, one
  native-Darwin test skipped, and 6 subtests passed.
- Migration/backup/restart qualification subset: 113 passed.
- Native-repair focused audit suite: 86 passed and one native-Darwin test
  skipped; the Auditor returned PASS with no remaining findings.
- Ruff, strict mypy (123 files), compileall, shell syntax, and
  `git diff --check`: passed.
- Wheel build and isolated no-dependency install: passed at package `0.3.0`.
- Installed CLI version/help/launch/install-launcher/schedule/status/doctor:
  passed at schema `18` and config `5` in an isolated runtime directory.
- Fresh read-only audit verdict: PASS, with no remaining blocker, important, or
  minor code findings.
- Added macOS GitHub Actions coverage for Python 3.11 package installation,
  full pytest, static checks, wheel build, and CLI help. It has not run remotely
  because this task does not authorize a push.

The native `libproc` integration test is intentionally skipped on non-Darwin
hosts and is configured to run on the macOS CI runner. The required real-Mac
Finder, singleton, Codex, lifecycle, cancellation, fallback-port, and launchd
acceptance is complete. Login/logout or full Mac restart was not reported and
is the sole deferred environment smoke; it is not a failure of the qualified
implementation.
