# Changelog

## [0.4.1] - Unreleased

### Added

- Exact GitHub Release end-user asset set: a universal wheel, a shared
  standard-library installer core, thin macOS and Windows/WSL entry points, and
  `SHA256SUMS`.
- Versioned private runtimes below the established platform data directory,
  with wheel-hash provenance, atomic current/prior runtime records, and exact
  native scheduler snapshots for rollback.
- Safe normal uninstall that preserves personal data and requires an explicit
  choice before removing an installed schedule; destructive data purge requires
  a separate exact confirmation phrase.

### Changed

- Ordinary-user installation no longer requires a Git clone, retained source
  checkout, manual virtual environment, tests, campaign records, CI files, or
  developer tools.
- Owned desktop launchers and existing owned schedules can be repointed to the
  verified private runtime. Schedule time and enabled/disabled state are
  preserved, and no schedule is created when none existed.
- The wheel excludes the deterministic fake analyzer used only by tests and is
  emitted with actual DEFLATE compression.

### Compatibility

- Scientific and digest runtime semantics are unchanged from v0.4.0.
- SQLite schema remains version 18.
- JSON config remains version 5.
- UI registration remains version 1.
- No user-data migration is required for this packaging change.

### Release status

- Candidate packaging only. No v0.4.1 tag, GitHub Release, or published asset
  exists until the release procedure is explicitly authorized and completed.
- Clean release-asset-only human smokes on macOS and Windows/WSL remain release
  acceptance steps after candidate artifacts are staged.

## [0.4.0] - 2026-08-27

### Added

- First-class Windows 11/WSL2 and native macOS application launchers with
  exact owned-process validation, singleton UI-server reuse, and bounded
  fallback ports.
- Native macOS launchd automation alongside the existing Windows Task
  Scheduler backend.
- Application-controlled digest cancellation, durable progress, UI
  reattachment, and safe run-owned provider-process termination.
- Source-provided author metadata in article headers across Today, History,
  Library, calibration, and related evidence displays.
- A guarded macOS bootstrap that refuses Python older than 3.11 before virtual
  environment creation.

### Changed

- Source coverage is scoped only to source/category/date semantics and is
  independent from Interest Profile analysis state.
- Successfully retrieved source-date corpora are reusable across retries,
  profile edits, UI restarts, and process restarts.
- Completed article analyses are reusable across retries and restarts when
  their profile and analysis semantics are unchanged.
- Browser, UI-server, digest-worker, and scheduler lifetimes are explicitly
  independent. Closing or stopping the UI does not cancel active work.
- Windows/WSL and macOS process ownership and cancellation use exact native
  process identity instead of PID-only or broad process-name signaling.

### Compatibility

- Requires Python 3.11 or newer.
- SQLite schema remains version 18.
- JSON config remains version 5.
- UI registration remains version 1 and stays backward compatible with prior
  version-1 registrations.
- No data or configuration migration is required solely for v0.4.0.

### Qualification

- Windows 11 with WSL2 and macOS are human-qualified on their tested
  environments.
- Finder launch, real Codex-backed analysis, native cancellation, UI
  reattachment, fallback ports, and launchd invocation passed on real Mac
  hardware.
- Windows launch plus real Codex execution immediately after `wsl --shutdown`
  remains a deferred environment smoke.
- macOS login/logout or full-restart smoke remains deferred.
