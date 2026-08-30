# Library L1-C canonical summary lifecycle

L1-C makes `AIArtifact` the sole durable owner of every newly generated summary
body while preserving schema-19 summaries as a read-only compatibility class. It
adds lazy summary generation only inside the existing paper-detail `AI Summary`
section. At the L1-C freeze, the inherited L1-B order was My Notes, Abstract, AI
Summary, then AI Discussions.

## Pre-change ownership audit

The digest provider returns a required in-memory `AnalysisResult.summary`. The
digest prompt includes the active Interest Profile as well as Article metadata,
so the current digest summary may be profile-influenced. Before L1-C,
`Database.upsert_analysis` stored that body in the non-null
`relevance_analyses.summary` column. Cache identity is the unique tuple
`(article_id, profile_id, profile_fingerprint)`; the fingerprint covers the
prompt-visible profile semantics, not Article content or provider/model routing.

On a cache hit, the pipeline reconstructs `AnalysisResult` from that row without
calling a provider. Today renders `DigestItem.analysis.summary` directly. The
deterministic cross-paper synthesis reads relevance facts and Article identity,
not the summary body. History snapshots copied `summary` and adjacent analysis
fields into JSON, while History reconstruction normally reloaded the analysis
cache. Full SQLite backup preserved the inline row and snapshot; the JSON export
deliberately treated relevance analysis as replaceable cache data.

The L1-A Library resolver already checked explicit `library_summary` artifacts,
then `digest_summary` artifacts, then the newest inline relevance summary. Thus
the smallest forward fix is one nullable pointer rather than a second ownership
or preferred-summary framework.

## Schema 20 and legacy compatibility

Schema 20 additively introduces:

```text
relevance_analyses.summary_artifact_id
    NULL, or REFERENCES ai_artifacts(id) ON DELETE SET NULL
```

It also adds a partial index on non-null analysis pointers and an index on
`ai_conversations.rolling_summary_artifact_id` for bounded GC protection checks.
The partial pointer index stores no entry for grandfathered rows.

The existing non-null `summary` column remains for compatibility. A new
canonical row stores an empty string there and points to its one
`digest_summary` artifact. A pre-L1-C row retains its exact inline body and a
NULL pointer. Migration neither reads nor copies prose, rewrites History, nor
calls a provider. It uses the established pre-migration backup and transaction;
reopening schema 20 performs no migration or second backup.

Resolver precedence remains deterministic:

1. newest live explicit `library_summary` artifact;
2. newest live `digest_summary` artifact;
3. newest grandfathered inline analysis whose pointer is NULL;
4. no summary.

Retention is authoritative for new canonical artifacts only. Grandfathered
inline relevance and History prose intentionally remain outside the 90-day
policy, without mass normalization.

## New digest writes and cache reuse

After a successful provider analysis, the pipeline derives model-neutral
provenance and an input fingerprint from all prompt-visible Article and profile
fields plus provider/model/generator identity. One immediate SQLite transaction:

1. inserts the summary body once as `AIArtifact(type=digest_summary)`;
2. inserts or updates the relevance facts with empty inline summary and the
   artifact ID;
3. applies the saved-paper preferred retention rule.

An unsaved paper receives `TEMPORARY` retention and the named 90-day expiration.
For a saved paper with no explicit Library summary, the new digest artifact is
the one `LIBRARY` default and the prior ordinary digest default receives a new
90-day grace period. If an explicit Library summary exists, it remains preferred
and the new digest summary stays temporary.

A canonical cache hit resolves its linked live artifact and performs no model
call or content copy. An expired or deleted canonical artifact does not resurrect
an empty inline value as a cache hit. A legacy cache hit continues reading its
inline body and is not normalized merely because it was reused.

## Save, unsave, and replacement

Save is zero-AI. It resolves the current live preferred artifact and promotes
that same row to `LIBRARY`, clearing expiration. It does not copy legacy prose or
retain every old digest version. Other ordinary retained summary artifacts move
to `TEMPORARY` with a 90-day grace period. `USER_PINNED` is never changed.

Unsave is also zero-AI. Ordinary `LIBRARY` digest and Library summaries become
`TEMPORARY` with a new 90-day grace period. It does not delete immediately or
alter grandfathered inline prose.

Successful explicit regeneration first inserts the replacement Library artifact
and only then demotes the previous nonpinned summary artifacts in the same
immediate transaction. Provider failure writes nothing. SQLite failure rolls
back insertion and retention changes together, so the previous preferred
summary remains retained.

## Lazy explicit Library generation

The detail page displays a passive Generate control only when resolution returns
none and a passive Regenerate control when a summary exists. Both remain below
the stored Abstract. No control is present in the dense list.

The provider is constructed only inside a clicked action. Normal Generate first
looks for a live artifact matching Article source fingerprint,
generator-version, and provider/model policy and reuses it without a call.
Regenerate deliberately calls once. A per-Article Streamlit request guard blocks
rerun/double-submission duplication in one browser session.

The bounded source context is deterministic JSON containing only title, authors,
and stored abstract, with a 64 KiB UTF-8 ceiling. Output has an 8 KiB UTF-8
ceiling, while the prompt requests no more than 150 words focused on central
claim/result, method, and implication. There is no PDF fetch, browsing, profile,
History, conversation, Library-context, or Atlas input.

`LibrarySummaryProvider` is model-neutral. The production adapters use the
currently configured OpenAI or Codex provider/model without a config-version or
model-selection UI change. Provider, model ID, available reasoning effort,
generator version, and input fingerprint are artifact provenance, not Library
core semantics. The boundary is the future hook for dedicated routing.

## History and garbage collection

New snapshots store summary ownership kind, stable ID, date, and provenance, but
not canonical summary prose. Legacy snapshots with an inline `summary` remain
readable. History resolves artifact and legacy references in at most two batched
reads for the whole snapshot. If a temporary artifact expires or is deleted,
the snapshot retains Article/run facts and displays:

> AI summary expired under retention policy.

Snapshot references are JSON identifiers, not foreign keys, so they do not keep
unsaved temporary prose alive forever.

GC runs once after the durable terminal boundary of a direct or service-level
digest run, including failed/cancelled terminal states. Cleanup failure cannot
change the scientific run verdict. It performs no model work and deletes only
expired `TEMPORARY` artifacts without a live rolling-conversation-summary
reference. `LIBRARY` and `USER_PINNED` rows are outside the candidate query.
Relevance-analysis pointers clear through `ON DELETE SET NULL`; analysis and
History facts, Articles, notes, feedback, Library membership, and conversations
survive.

The candidate query uses the retention/expiry covering index and the rolling
summary reference index. There is no page-render cleanup, polling loop, or new
scheduler.

The dense Library list still performs no summary-body query. One detail view
uses a constant one-to-three resolver reads depending on which precedence branch
succeeds. A 1,000-item mixed History fixture performs exactly one artifact batch
read and one legacy-analysis batch read, rather than one query per item.

## Backup and storage measurements

Full SQLite backup naturally preserves artifact, pointer, retention, provenance,
and snapshots. JSON export now includes artifact rows plus a prose-free mapping
from relevance-analysis identity to summary artifact ID. It never exports
credentials.

The repository's representative pre-L1-C database contains 21 nonempty inline
summary rows totaling 3,480 UTF-8 bytes. They remain grandfathered. Synthetic
schema-20 qualification uses 768-byte summary bodies and representative
provenance strings:

- An `AIArtifact` row uses 182 table-payload bytes excluding content. Its three
  artifact indices use about 184 bytes per row at 100 rows and 188 bytes per row
  at 1,000 rows. Provenance length changes these values linearly.
- A non-null analysis pointer adds 1.872 table-payload bytes per row across 1,000
  rows. Its partial index adds 6.744 payload bytes per linked row and zero payload
  bytes for NULL legacy rows. The linked 1,000-row case allocated three more 4
  KiB pages than the all-NULL case.
- Deleting 100 representative temporary summaries reclaimed 95,000 bytes of live
  artifact-table payload: 76,800 content bytes plus 18,200 row overhead. Deleting
  1,000 reclaimed 950,000 live payload bytes. The measured GC transactions took
  0.746 ms and 4.309 ms respectively on this qualification host.
- SQLite allocated-file size stayed unchanged after DELETE (446,464 bytes for
  the 100-row fixture and 1,687,552 bytes for the 1,000-row fixture); 30 and 333
  pages became freelist capacity for reuse. Live-payload reclamation is distinct
  from filesystem compaction.
- Newly generated summary prose duplicated durably across artifact, relevance,
  History, or Library state: **0 bytes**.

## Four-cost assessment

| Component | Human attention | Local storage | AI tokens | Upgrade cost |
|---|---|---|---|---|
| Canonical digest summary | Today and Library resolve the same useful body without migration detail in the UI | One body; one nullable pointer; legacy NULL rows consume no partial-index payload | One already-authorized digest call, then zero-call cache/display reuse | Model-neutral artifact provenance replaces inline ownership for future writes |
| Explicit Library summary | One subordinate detail action; concise result stays below Abstract | One preferred body; replaced nonpinned bodies become reclaimable after grace | Only explicit Generate/Regenerate; compatible Generate reuses | Stable provider protocol and routing hook avoid a Library-core migration |
| Save/unsave transitions | Saving immediately reuses available work; unsave has a non-destructive grace period | Retention flags change on the same row, with no copy | Zero | Policy stays in artifact service, independent of page/provider |
| History compatibility | Old and new runs look coherent; expiry is stated plainly | New snapshots store a small reference, not prose; old snapshots remain bounded compatibility data | Zero display/regeneration | Dual reader permits additive rollout without destructive snapshot rewrite |
| GC | No page latency or surprise immediate loss | Expired temporary bodies become reusable SQLite space; user/source rows are unreachable | Zero | One deterministic primitive at an existing terminal boundary, no scheduler |
| Provider boundary | Failure is actionable and sanitized; existing summary remains visible | Provenance only; no credentials or prompt cache | Authoritative usage is retained only where providers expose it; never estimated | OpenAI/Codex adapters implement one small model-neutral contract |

This stops future digest-summary duplication, permits unsaved canonical summaries
to expire, reuses the same artifact on save, keeps explicit Library generation
lazy, and permits later provider/model routing changes without another Library
schema redesign.

## Deliberately deferred

L1-D conversation execution/context compression, model-selection UI, PDF/full
paper summarization, Research Atlas, semantic search, automated Library
enrichment, historical summary normalization, and any Library list/detail
hierarchy redesign remain out of scope.

## Qualification state

The final deterministic gate before human smoke passed with 677 tests, 5 skips,
and 41 subtests. Ruff, strict mypy over `src` and `tests`, compileall, and
`git diff --check` passed. The focused Library/schema/cache/Today/History/GC/
zero-AI/scheduler/cancellation/distribution selection passed, as did all
Streamlit AppTests in the complete suite. An exact Streamlit 1.51.0 floor run
passed 17 tests and 7 subtests. A freshly built 0.4.1 wheel installed in an
isolated environment and passed the representative Generate/refresh, detail
hierarchy, History-expiry, and Streamlit-signature tests.

A fresh read-only focused Auditor returned PASS after identifying one History
reconstruction edge case during review. The repair ensures an old snapshot's
expired artifact state cannot be replaced by a later same-profile cache summary;
the new adversarial regression passes. The Auditor's only residual observation
is non-blocking: the UI request guard is browser-session-local, so simultaneous
explicit requests from separate sessions may each spend a provider call, while
the immediate transaction still leaves only one ordinary retained default.

The human browser smoke passed on the disposable no-network fixture. Legacy
inline and canonical artifact summaries both rendered below Abstract with zero
provider calls, and the frozen detail hierarchy remained My Notes, Abstract,
AI Summary, AI Discussions. Generate and Regenerate each caused exactly one
intentional provider call; replacement became preferred only after successful
persistence, and the previous summary moved to TEMPORARY with its grace period.
Save/unsave, History rendering, navigation, and refresh caused zero provider
calls. History retained run facts after test-artifact expiry and rendered
"AI summary expired under retention policy." Persisted state and retention
transitions survived refresh. The fixture did not touch the real Library.

This human smoke closes L1-C qualification and authorizes the local freeze. It
does not authorize a push, tag, release, or any L1-D behavior.

## Final L1 milestone hierarchy amendment

Final L1-D human validation intentionally superseded the earlier L1-B/L1-C
presentation contract. The active hierarchy is Abstract, My Notes, AI Summary,
then AI Discussions: authoritative source first, user interpretation/work next,
and AI-derived interpretation/discussion last. The original L1-C smoke and
freeze above accurately record the order tested at that time. This later UI-only
amendment does not change canonical summary ownership, lazy generation,
retention, GC, History, provider routing, or any schema-20 persistence behavior.
