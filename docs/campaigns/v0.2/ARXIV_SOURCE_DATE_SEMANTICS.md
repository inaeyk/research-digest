# arXiv Source-Date Semantics

U2-A defines arXiv source date as the UTC calendar date of the official Atom
API entry `published` timestamp.

Rationale:

- The existing v0.1.0 adapter already normalizes the official Atom `published`
  timestamp into `Article.published_at`.
- The official arXiv API exposes a `submittedDate` search filter using
  `YYYYMMDDHHMM` in GMT and supports `sortBy=submittedDate`.
- U2-A retrieval uses `submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]` to bound
  API pages and then classifies returned entries by `Article.published_at`
  converted to UTC date.
- The same UTC source-date interpretation must be used by retrieval, tests,
  later History metadata, scheduler catch-up, and UI labels.

Important non-goals:

- Streamlit local timezone dates must not be silently mixed with arXiv UTC
  source dates.
- U2-A does not model a separate daily-announcement date because the existing
  official API path used by Research Digest does not expose that as a distinct
  per-entry field.
- If a later stage finds a separate official arXiv daily-announcement date that
  materially changes user-visible behavior, the campaign must stop for human
  authority before changing source-date semantics.
