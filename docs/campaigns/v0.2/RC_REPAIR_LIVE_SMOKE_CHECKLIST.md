# RC Repair Human Live Smoke Checklist

Use this checklist in a normal local environment with network access, Streamlit
socket binding, and the qualified analyzer/provider configuration available.
The sandboxed agent environment could not bind a local serve socket and could
not reach live arXiv, so these checks remain human live-smoke items rather than
deterministic qualification failures.

## Source-Date Contract

- Source dates use America/Chicago.
- Papers are assigned by their arXiv publication timestamp converted to
  Chicago local time using timezone database rules.
- API `submittedDate` ranges are candidate windows only; final date membership
  is decided by local conversion of the stored publication timestamp.
- Do not compare counts to arXiv mailing/listing pages as an acceptance
  criterion if those pages use different cutoff semantics.
- For a selected source date, include qualifying papers in the configured
  categories after Chicago-local filtering.
- Deduplicate the same arXiv paper across selected categories.
- Exclude replacement/update-only entries unless their arXiv publication
  timestamp belongs to the selected Chicago source date.

## Manual Digest

- Select a known arXiv source date with categories `hep-th` and `gr-qc`.
- Verify retrieved article membership by converting each paper's arXiv
  publication timestamp to America/Chicago and comparing to the selected date.
- Include a boundary check with a publication timestamp near Chicago midnight
  if a suitable live paper or stub source is available.
- Confirm the run proceeds through bounded multi-chunk Codex full analysis
  without wholesale failure when one large structured response would be too
  large or incomplete.
- If safely reproducible with a test provider/stub, force one chunk omission or
  malformed item and verify only the missing paper is retried.
- Verify successful analyses from earlier chunks are not re-requested after a
  later chunk failure.
- Verify synthesis is produced from available valid analyses and does not imply
  full analysis if unresolved papers remain.

## Abstract Display

- In the Today result view, inspect an above-threshold paper and toggle
  `Show abstract` / `Hide abstract`.
- In the Today result view, inspect a below-threshold paper and toggle
  `Show abstract` / `Hide abstract`.
- In the Today result view, inspect a preselected-out paper and toggle
  `Show abstract` / `Hide abstract`.
- In History, open analyzed and preselected-out paper snapshots and verify the
  same abstract toggle behavior.
- Confirm toggling abstracts does not trigger new analyzer/Codex calls and does
  not mutate run, relevance, cache, or feedback state.

## Automation

- Open Settings -> Automation and edit `Catch up from`.
- With `Catch up from` later than the latest available source date, verify the
  UI shows this as a benign zero-pending state, not an error.
- Verify the UI explains that earlier successfully digested dates are not
  reprocessed, failed/incomplete dates remain pending, moving the anchor earlier
  can add pending dates, and moving it later does not delete history/coverage.
- Verify pending dates update for the active profile and source/category
  semantics.
- Click Run Now when pending dates are `none`; verify no History run is
  created and a visible message explains the catch-up anchor and latest
  available source date.
- Move `Catch up from` earlier so pending dates exist; click Run Now and verify
  it invokes the same automatic catch-up service used by scheduled execution,
  shows progress/result, and refreshes History plus the coverage calendar.
- Change categories, for example from `hep-th`/`gr-qc` to `astro-ph.CO`, and
  verify prior status is not incorrectly shown as completed for the new source
  semantics.
- Use Run Now and verify scheduled catch-up uses the same source-date semantics
  as manual date selection.

## Date Status Calendar

- Inspect the date-status grid next to manual date selection and in Automation.
- After a successful manual single-date digest, verify the selected date is
  shown as selected and completed, not selected and pending.
- Verify completed digest, failed digest, partial/incomplete digest,
  successfully checked/no submissions, pending/uncovered, and currently
  selected states are visible by text/labels, not color alone.
- Verify pending/uncovered appears only for dates inside the catch-up interval.
  Dates before `Catch up from` and after latest available should be neutral
  unless they have durable historical status.
- Verify completed dates require a usable completed digest under the current
  profile/source semantic scope.
- Verify failed or incomplete dates remain pending for retry.
- Verify a successful retry after an earlier failed/partial attempt changes the
  current calendar state to completed while History still shows both attempts.
- Verify no-submission dates are shown separately from completed paper digests.
- Verify day cells do not contain long wrapped strings such as
  `Pending/uncovered`; use the legend/details table for full status text,
  selected overlay, run id, and counts.

## Category-Order Source Identity

- Save categories as `hep-th` and `gr-qc`.
- Verify Aug 12 through Aug 14 remain completed for the active profile/source
  scope.
- Reverse only their order to `gr-qc` and `hep-th`, then save.
- Verify Aug 12 through Aug 14 still remain completed.
- Verify pending dates are unchanged.
- Verify no new History run is created by saving the reordered category list.
- Verify no analysis rerun occurs merely because the category list was
  reordered.
- Replace one category, for example `gr-qc` with `astro-ph.CO`, and verify a
  distinct source scope is created.

## Scheduler Smoke

- Install or update the daily schedule through the Settings UI.
- Inspect the Windows Task Scheduler action and confirm it invokes the shared
  scheduler/headless service path through WSL.
- Confirm the scheduled environment includes the Codex executable directory in
  `PATH` when Codex analysis is configured.
- Confirm no API key, token, Codex auth file, or local auth path is embedded in
  the scheduled task.
- Trigger the task and verify WSL can run `research-digest`, Codex is
  available, the digest reaches a terminal outcome, and UI/History show the
  scheduled result.
