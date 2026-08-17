# arXiv Source-Date Semantics

Human authority decision for v0.2: Research Digest source dates use
America/Chicago.

Decision:

- Research Digest does not attempt to reconstruct or duplicate arXiv mailing,
  announcement-day, or daily-listing cutoff semantics.
- For an arXiv article, the authoritative Research Digest source date is the
  calendar date obtained by converting the article's authoritative arXiv
  publication timestamp to the IANA timezone `America/Chicago`.
- The conversion is timezone-aware, not a fixed UTC offset. CST/CDT transitions
  follow timezone database rules.
- The same source-date helper is used by single date, date range, selected
  dates, latest available, scheduler catch-up, `Catch up from`, coverage
  state/calendar, History, and run snapshots.

Retrieval contract:

- The arXiv API `submittedDate` filter may be used only to retrieve a safe
  superset of candidate records.
- Query windows are padded around Chicago-local source-date boundaries so
  DST/boundary effects cannot omit candidates before local filtering.
- Final date membership is always decided locally:

  ```text
  Atom published timestamp -> America/Chicago conversion -> source_date
  ```

- Papers qualify by configured arXiv categories and are deduplicated by stable
  arXiv article identity.
- Replacement/update-only records are not included merely because an update
  timestamp falls in a query window; source-date membership uses the arXiv
  publication timestamp stored on `Article`.

User-facing wording:

- Prefer: `Source dates use America/Chicago.`
- Prefer: `Papers are assigned by their arXiv publication timestamp converted
  to Chicago local time.`
- Do not call this an arXiv announcement date, mailing date, or listing date.
- Do not promise counts will match arXiv mailing/listing pages if those pages
  use different cutoff semantics.
