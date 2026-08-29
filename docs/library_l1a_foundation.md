# Library L1-A persistence foundation

L1-A is an additive persistence substage. It does not add Library, paper-detail,
summary-generation, or conversation UI, and it never performs AI work.

## Pre-change schema audit

- Package/runtime version: `0.4.1`; config version: `5`; SQLite schema: `18`.
- `articles.id` is the canonical local paper identity. `UNIQUE(source,
  source_article_id)` preserves source identity while allowing source metadata to
  be refreshed in place.
- `library_articles` is a save relationship keyed by `article_id`; it does not
  own Article metadata.
- `library_article_notes` already provides one durable human note per Article.
  Its `note_text` is Markdown content and remains the sole note body.
- Collections and memberships, tags and provenance-bearing assignments, and AI
  tag suppressions are already normalized by stable IDs.
- Relevance analyses are cached by Article, profile, and profile fingerprint.
- Run facts and source-date coverage/corpora are normalized, while `run_snapshots`
  deliberately retain immutable historical JSON from earlier releases.

## Generated-prose persistence inventory

| Persisted data | Canonical owner | Duplicated elsewhere | History copy | Library copy | Cache/reuse | L1-A decision |
|---|---|---|---|---|---|---|
| `relevance_analyses.summary` | Article/profile/fingerprint analysis row | Existing History snapshot item | Yes | No; L1-A resolves it directly | Yes, analysis cache | Keep in place; use as the legacy digest-summary fallback without copying |
| `relevance_reason`, `why_it_matters`, `reading_priority`, matched topics | Analysis row | Snapshot copies summary-adjacent `why_it_matters` and priority | Partial | Library reads only latest score/priority context | Yes | Do not split the mixed analysis cache in an additive migration |
| `preselection_decisions.reason` | Run/article decision evidence | Run snapshot preselection item | Yes | No | Durable decision evidence | Keep; not one of the three artifact types |
| AI tag names and `ai_provenance_json` | Tag identity plus Article/tag/origin assignment | Backup export only | No | Direct normalized relationship | Upsert/regeneration reuses assignments | Keep; it is structured provenance, not generic prose |
| `library_article_connections.rationale` | Canonical Article-pair connection row | Backup export only | No | Directly rendered from the owner row | Unique pair/upsert | Keep; moving it would add pointer churn without reducing a live copy |
| `library_context_suggestions.rationale` | Article/related-Article/collection suggestion row | Backup export only | No | Directly rendered from the owner row | Unique relationship/upsert | Keep for compatibility; Atlas integration is deferred |
| `collection_intelligence_snapshots.summary` | Collection snapshot | Backup export only | No | Direct snapshot read | Multiple intentional snapshots | Keep; current generation is deterministic and collection-scoped |
| suggested-interest description/explanation | Suggested-interest row | Backup export only | No | No | Stable deterministic suggestion | Keep; current producer is deterministic |
| `run_snapshots.snapshot_json` item prose and Article fields | Historical run snapshot | Copies canonical Article and analysis fields | It is History | No | Immutable per run | Preserve exactly; establish an expiration-aware future read path instead of rewriting history |
| `library_search_documents.document_text` | Replaceable local search cache | Repeats Article/note/tag/collection/relevance text | No | Search only | Rebuilt deterministically | Keep as a replaceable search component; do not mix with stable Library state |
| cross-paper synthesis fields | Run snapshot | Titles repeat Article titles | Yes | No | Rebuilt per digest | Keep; current synthesis is deterministic, not model prose |

Raw provider responses are not persisted separately. The authoritative parsed
analysis or generated relationship object is stored once, apart from the known
legacy History snapshot copies above.

## Schema 19 design

`library_articles` gains two nullable constrained columns:

- `reading_state`: `NULL`, `unread`, `skimmed`, `read`, or `reference`.
- `interest_rating`: `NULL` or an actual SQLite integer from 1 through 5.

Migration leaves both columns `NULL` for every existing row. Saving never assigns
either value. Unsave preserves explicit user state and never creates negative
feedback.

`ai_artifacts` stores replaceable generated content once and points to
`articles.id`. Its artifact types are exactly `digest_summary`,
`library_summary`, and `conversation_summary`. Provider, model ID, reasoning
effort, generator version, and input fingerprint are provenance rather than
Library semantics. Retention is constrained to `TEMPORARY`, `LIBRARY`, or
`USER_PINNED`; temporary rows require an expiration and retained rows forbid one.

`ai_conversations` is an Article-linked transcript header with model-neutral
provenance and an optional pointer to a same-Article `conversation_summary`
artifact. `ai_conversation_messages` stores only conversation ID, deterministic
sequence number, role, content, and creation time. It has no Article metadata and
does not share storage with the user note.

No preferred-summary pointer is stored. Resolution is deterministic:

1. newest usable explicit `library_summary` artifact;
2. newest usable retained `digest_summary` artifact;
3. newest existing `relevance_analyses.summary` by direct reference;
4. no summary.

This makes saving and opening the Library zero-AI operations and introduces no
migration-time prose copy.

## Retention and garbage collection

`DEFAULT_TEMPORARY_AI_ARTIFACT_RETENTION` is the single 90-day default. The
expiration helper accepts an alternate positive period for policy injection and
tests.

- An unsaved digest artifact starts `TEMPORARY` and expires after the policy
  period.
- Saving before expiration promotes the same temporary row to `LIBRARY` and
  clears expiration. An already-expired row remains temporary and eligible for
  deterministic cleanup; save never resurrects stale prose.
- Unsaving demotes the same `LIBRARY` row to `TEMPORARY` and starts a new grace
  period.
- `USER_PINNED` is never changed by save/unsave and never expires.

The explicit GC primitive deletes only expired `TEMPORARY` rows whose Article is
not saved and whose artifact ID is not a rolling-summary reference. It performs
no AI work and has no SQL path to notes, Articles, Library membership, feedback,
or conversations. L1-A does not schedule or invoke GC automatically.

Existing `relevance_analyses` rows remain the legacy analysis cache. Applying
artifact retention to their summary text would require splitting a mixed,
non-null analysis record and changing History reconstruction. L1-A therefore
does not create metadata-only pseudo-artifacts or duplicate 672 representative
cached summaries. A later lossless analysis-cache split can make legacy prose
expirable; History can then render an explicit “AI summary expired under
retention policy” state while preserving run facts. Existing snapshots are not
rewritten.

## L1-C canonical-summary ownership preregistration

L1-C must establish one canonical owner for each **newly generated** digest
summary body. New summary prose must not be stored indefinitely in both
`relevance_analyses.summary` and `ai_artifacts.content`. The authoritative body
must be the object governed by the 90-day unsaved-paper retention policy, with
the other subsystem resolving it by stable reference or another zero-copy
mechanism.

This is a forward-looking ownership requirement, not authorization to mass-copy,
rewrite, or delete historical analysis summaries or History snapshots. L1-C
must preserve L1-A's deterministic legacy fallback while introducing canonical
ownership for new generation.

## Migration behavior

Schema 19 uses the existing pre-migration SQLite backup mechanism and a single
transaction. It adds columns with `NULL` defaults and creates empty tables and
indices. It does not read prose into Python, insert artifact rows, update History,
or call a provider. Reapplying the table/column creation is safe, and reopening a
schema-19 database does not create another migration backup.

The JSON backup export includes the new Library state, artifacts, conversations,
and messages. SQLite backups already preserve all tables byte-for-byte.

## Measured storage cost

Measurements use SQLite `dbstat` payloads and allocated page counts. The
representative schema-18 database had 875 Articles, 18 saved papers, 672 analyses,
and 28 History snapshots.

- Existing migrated Library rows: 0 payload bytes added; SQLite `ALTER TABLE`
  does not rewrite them.
- New schema-19 Library row with both new values `NULL`: 47 bytes versus 45
  bytes in schema 18, or 2 additional record-payload bytes.
- Empty conversation with representative title/provider/model strings: 94 table
  payload bytes plus 25 explicit-index payload bytes (119 bytes, excluding shared
  B-tree pages).
- Representative AI artifact metadata: 128 table-payload bytes excluding its
  one-byte content, plus 135 bytes across the three artifact indices. This varies
  linearly with provenance string lengths.
- Representative database migration: 5,210,112 to 5,246,976 allocated bytes,
  an increase of 36,864 bytes for the new empty tables/indices and schema text.
- No prose bytes are duplicated by migration.

Transcript sizing uses 20 alternating messages and a disk-planning scenario of
four UTF-8 text bytes per named token. This is not AI token accounting:

| Scenario | Stored text bytes | Message-table payload | Message-index payload | Allocated-file delta |
|---|---:|---:|---:|---:|
| 10k-token-sized transcript | 40,000 | 40,709 | 118 | 40,960 |
| 20k-token-sized transcript | 80,000 | 80,709 | 118 | 81,920 |
| 50k-token-sized transcript | 200,000 | 200,729 | 118 | 204,800 |

Schema 19 adds four named indices and one SQLite unique index:

- Article/type/creation ordering for preferred artifact resolution;
- Article/type/input fingerprint ordering for reuse;
- retention class/expiration for GC;
- Article/update ordering for conversation listing;
- unique conversation/sequence ordering for messages.

## Four-cost assessment

| Component | Human-attention cost | Local-storage cost | AI-token cost | Upgrade cost |
|---|---|---|---|---|
| Library core | Save remains one action; rating/state stay unset until explicit judgment | Two nullable fields, measured at 2 payload bytes on a new unset row | Zero for save, unsave, reads, and edits | Stable user state remains separate from analysis/profile scoring |
| Notes | Existing one-note workflow and exact Markdown are preserved | No new table or copied note body | Zero; AI has no note mutation path | Existing Article pointer can later support revisions/search/Atlas extraction |
| Artifact store | Later UI can reuse a preferred result without asking the user to regenerate | One content body plus provenance; migration copies zero prose | Creation APIs persist completed output only; resolution/promotion/GC are zero-AI | Model-neutral types and provenance make generators replaceable |
| Retention/GC | No immediate loss on unsave; 90-day grace is automatic state only | Expired unreferenced derived rows can be reclaimed deterministically | Zero; GC never calls a model | Named policy and safety predicates can be scheduled later without schema change |
| Conversations | Multiple discussions and complete ordered transcripts are durable | One header per discussion; content stored once per message | Persistence is zero-AI; later context compression is opt-in policy | Provider/model provenance and nullable rolling-summary pointer avoid binding core storage to one model |
| Migration | Existing papers, notes, tags, collections, feedback, coverage, and History need no user repair | 36 KiB measured one-time empty-schema increase; no prose duplication | Zero | Additive, backed up, transactional, and replay safe; legacy History is not destructively normalized |

## Deliberately deferred

L1-B dense Library UI, L1-C summary generation/display controls, L1-D
conversation execution/UI, automatic GC scheduling, History redesign, Research
Atlas, graph/citation sources, embeddings, and model-selection UI remain out of
scope.
