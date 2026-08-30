# Library L1-D: durable bounded AI discussions

## Scope and frozen baseline

L1-D starts from L1-C commit
`c52f318b9df539ee5b87b20e7db7a6ff3606f8ed`. Package/runtime remains 0.4.1,
SQLite schema remains 20, and config remains 5. L1-D was initially implemented
against the inherited L1-B/L1-C paper-detail order:

1. My Notes
2. Abstract
3. AI Summary
4. AI Discussions

The first full L1-D human smoke passed functionally, then final L1 milestone
validation intentionally amended and superseded that inherited order. The
active hierarchy is now:

1. Abstract
2. My Notes
3. AI Summary
4. AI Discussions

This presents authoritative paper source before the user's interpretation/work,
with AI-derived interpretation and discussion last. The dense Library list and
all persistence, retention, context, and provider semantics remain unchanged.

No Research Atlas, PDF retrieval, web browsing, citation ingestion,
paper-to-paper graph, AI title generation, or model-selection UI is introduced.

## Pre-change conversation-foundation audit

Schema 20 already contained the stable facts L1-D needs:

- `ai_conversations` points to one canonical Article and stores a human-visible
  title, timestamps, model-neutral provider/model provenance, conversation
  version, and nullable `rolling_summary_artifact_id`.
- `ai_conversation_messages` stores one role/content/timestamp per sequence and
  enforces `UNIQUE(conversation_id, sequence_number)`. It contains no copied
  title, authors, abstract, note, summary, collection, or tag data.
- messages cascade only when their conversation is explicitly/canonically
  deleted. Unsave changes Library membership and does not delete a conversation
  or transcript.
- the rolling pointer accepts only same-Article `conversation_summary`
  artifacts and uses `ON DELETE SET NULL`. The existing GC query protects every
  artifact referenced by that pointer.
- `idx_ai_conversations_article_updated` supports the compact per-paper list;
  the unique message index supports ordered transcript access; schema 20 also
  has `idx_ai_conversations_rolling_summary` for GC protection.
- SQLite backup and JSON export already preserve conversation rows, every
  message, every artifact/provenance field, and the rolling pointer.

Before L1-D, the service was persistence-only, the provider protocol had no
production adapters or compression operation, and the Library UI could only
inspect stored transcripts.

## Schema and exact rolling boundary

Schema remains **20**. No migration, field, table, or index is added.

The exact summarized boundary is stored in the pointed artifact's structured
input fingerprint:

```text
conversation-summary-boundary-v1:
conversation=<conversation_id>:
through=<assistant sequence>:
sha256=<compression-input digest>
```

This is deterministic provenance, not a guessed boundary. The reader requires
the exact format, requires the conversation ID to match, and requires the
covered sequence to exist as an assistant message. Unknown/corrupt provenance
fails closed instead of silently dropping turns. Because the conversation
pointer and fingerprint identify one immutable artifact together, no separate
schema-21 state can drift from the selected summary. Backup/export already
preserves both. Encoding the exact boundary here avoids a migration without
overloading content or generator version.

The persistence transaction independently receives the intended assistant
sequence and requires it to equal the fingerprint's `through=` value before it
inserts an artifact or changes a pointer. Reader and writer use the same strict
parser. This closes the reviewed failure mode in which conflicting values could
make unsummarized messages disappear from later model context.

## Discussion UX

The AI Discussions section remains compact on paper detail. It lists only title,
message count, and last-updated date. `New discussion` accepts an optional human
title; blank titles are deterministic (`Discussion 1`, `Discussion 2`, ...).
Creating and renaming headers are local database operations and create no model
work.

Opening one discussion shows the full locally persisted transcript with native
Streamlit user/assistant chat containers. Provider/model provenance is one
secondary header caption, not repeated per message. The message form exists
only inside an opened discussion. If rolling context exists, a secondary caption
states the exact summarized-through message while also stating that the full
transcript remains stored.

Every assistant message offers `Add takeaway to My Notes`. This first exposes an
editable confirmation form. Only `Add to My Notes` changes the canonical human
note. It reuses the already-stored response, performs no provider call, creates
no extra artifact, and does not change the transcript.

## Send, failure, retry, and concurrency semantics

One normal Send performs these steps:

1. validate the current message against the UTF-8 budget;
2. acquire a durable per-conversation SQLite lease;
3. append exactly one user message under an optimistic expected sequence;
4. assemble bounded context and compress older turns only if it cannot fit;
5. invoke the response provider once;
6. append one assistant response only if the exact user message is still the
   durable last message;
7. update conversation route provenance/timestamp and release the lease.

The existing keyed `run_locks` table supplies the local lease under the isolated
name `ai-conversation:<id>`; digest locking continues to use only `digest`. Its
stale boundary is the greater of 15 minutes and two configured provider timeout
windows plus a 60-second persistence margin. This covers the only two permitted
calls in a threshold-crossing Send (compression, then response) while retaining
crash recovery. Different conversations remain independent.

If the provider is unavailable before invocation, the transcript is unchanged.
If invocation fails after the user message is accepted, that exact user message
remains visibly unanswered. No ambiguous assistant placeholder is stored. The UI
offers one explicit `Retry response`; it sends the same pending message without
duplicating it. Provider-internal automatic retries are not added. A concurrent
Send/Retry is rejected before another provider call while the lease is live.
Optimistic sequence and pending-message checks prevent duplicate sequence
numbers and stale overwrites even across browser sessions.

## Context policy

The assembler emits deterministic UTF-8 JSON whose section names encode source
authority:

- `authoritative_paper_source`: title and stored abstract;
- `user_authored_context`: bounded My Notes;
- `derived_ai_context`: optional preferred summary and rolling summary;
- `live_conversation`: every unsummarized recent message, ending with the current
  user turn.

History, tags, collections, relevance prose, other papers/conversations, URLs,
PDF text, web results, and Atlas data are absent. Long stable fields are
deterministically UTF-8-truncated with an explicit marker; accepted live messages
are never silently truncated or omitted. If every unsummarized message cannot
fit, compression must establish an exact boundary first or the request fails.

Default hard context budgets are:

| Component/policy | UTF-8 limit |
|---|---:|
| Total assembled context | 128 KiB |
| Title | 4 KiB |
| Abstract | 48 KiB |
| My Notes | 12 KiB |
| Preferred AI summary | 8 KiB |
| Rolling conversation summary | 16 KiB |
| Live unsummarized conversation | 40 KiB |
| Current user message | 16 KiB |
| Assistant response | 32 KiB |
| One compression source | 96 KiB |
| Final response-provider prompt | 136 KiB |
| Final compression-provider prompt | 104 KiB |

The abstract receives the largest stable-source budget; the current question is
validated before persistence and always remains verbatim. Actual UTF-8 bytes,
not character count, govern these limits. These byte measurements are context
planning only and are never reported as provider token usage.

## Compression and atomicity

Message count does not trigger compression. The service first attempts to fit
all messages after the current exact boundary. If either the 40-KiB live window
or the 128-KiB assembled request would be exceeded, it chooses the earliest
assistant-turn boundary that lets the remaining turns fit with a maximum-size
rolling summary. One compression call receives the prior rolling state plus the
exact newly covered messages. Its prompt preserves research goals, conclusions,
claims/equations described in text, unresolved issues, assumptions, corrections,
distinctions, uncertainty, and paper-location references while dropping filler.

The new artifact insert, conversation-pointer switch, and old-artifact retention
demotion form one `BEGIN IMMEDIATE` transaction. Failure before commit leaves the
old pointer/retention unchanged. After success, an unpinned unreferenced old
summary becomes TEMPORARY with the existing 90-day grace period; USER_PINNED or
still-referenced artifacts remain protected. The full message table is never
modified by compression and has no L1-D GC policy.

## Provider routing

`ResearchConversationProvider` has model-neutral response and compression
operations plus provenance properties. Production adapters cover Codex CLI and
OpenAI. Codex remains ephemeral, read-only sandboxed, `shell=False` through the
qualified runner, and bounded by the configured timeout. Its child environment
is a strict allowlist: `PATH`, `HOME`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TMPDIR`,
`TMP`, and `TEMP` when present. `HOME` preserves the Codex CLI's own ChatGPT
login discovery; no API-key, cloud, Git, project, database, `*_TOKEN`, or
`*_SECRET` variable is inherited. OpenAI uses the Responses API with strict
one-field JSON output, explicitly disables SDK retries (`max_retries=0`), and
uses the same configured bounded timeout. One explicit UI retry is therefore a
new visible call, not a hidden transport retry. Errors are sanitized in the UI;
credentials never enter conversation/artifact rows.

There is no config-version or model-selector change. L1-D uses the currently
configured analyzer provider and its configured model as the initial research
conversation route. That is an explicit temporary routing hook, not a claim that
the configured model is optimal. Each successfully persisted response updates
conversation-level route provenance, so later dedicated routing can replace this
policy without a core schema migration.

## Storage measurements

Measurements use SQLite `dbstat` live payload on the qualification host; allocated
file size includes unrelated schema/pages and is reported separately.

- empty conversation row: **90 payload bytes**;
- message metadata excluding one-byte content: **35.372 payload bytes/row**
  averaged across 1,000 rows;
- existing unique sequence index: **7.744 payload bytes/message** in that fixture;
- rolling-summary artifact row excluding one-byte content: **246.92 payload
  bytes/row** averaged across 100 rows with structured boundary fingerprints;
- its existing three artifact indices: **239.87 payload bytes/row** in that
  fixture;
- L1-D indices added: **zero**;
- duplicated paper/source content: **zero bytes**.

Disk-only transcript fixtures used one ASCII lexical unit plus separator per
notional unit; these are not model token counts or usage estimates:

| Disk-planning scenario | Text bytes | Message-table live payload | SQLite allocated file |
|---:|---:|---:|---:|
| 10,000 lexical units | 20,000 | 20,709 | 352,256 |
| 20,000 lexical units | 40,000 | 40,709 | 364,544 |
| 50,000 lexical units | 100,000 | 100,709 | 425,984 |

## Context-growth measurement

A deterministic no-network fixture with an 8,000-byte abstract, 4,000-byte note,
and 2,000-byte preferred summary produced:

| State | Assembled bytes | Live bytes | Live messages | Rolling bytes | Boundary |
|---|---:|---:|---:|---:|---:|
| Short first question | 14,336 | included in total | 1 | 0 | 0 |
| Long, still below threshold | 46,919 | 32,647 | 10 | 0 | 0 |
| After threshold compression | 48,664 | 34,373 | 7 | 24 | 4 |

The threshold crossing used one compression call and one response call; all 12
messages remained in SQLite. This demonstrates that repeated response input does
not grow with the full retained transcript. Provider token usage was not exposed
by the fake and is therefore unavailable, not estimated.

## Four-cost assessment

| Component | Human attention | Local storage | AI/context cost | Upgrade cost |
|---|---|---|---|---|
| Conversation creation | Optional title and immediate empty thread; no waiting | One 90-byte measured header; no paper copy | Zero calls, including title | Route provenance is model-neutral |
| Transcript storage | Full history remains inspectable after refresh/months | One normalized row/message; source context not copied | Stored history does not imply replay | Provider transport is absent from rows |
| Send | One form; failures become one clear pending question with explicit retry | User and successful assistant each stored once | One response call unless bounded compression is genuinely required | Service owns sequencing/context, not adapter |
| Context assembler | Source hierarchy makes authority legible to the model | No persisted context/session copy | Explicit per-component and total UTF-8 ceilings | Deterministic JSON contract is provider-neutral |
| Rolling summary | Human keeps full transcript and sees exact coverage metadata | One derived artifact; replaced summaries become reclaimable | Triggered by bytes, not every turn/message count | Versioned fingerprint and artifact provenance fail closed |
| Note promotion | Editable confirmation prevents silent authorship changes | Reuses transcript; only confirmed note text is durable | Zero additional calls | No AI-note linkage migration is imposed |
| Provider routing | Provenance is secondary, with no selector clutter | Credentials/transport are never stored | Uses only explicit Send/Retry path | Codex/OpenAI implement one narrow protocol |

## Qualification and human smoke state

The repaired final tree passes:

- complete suite: 703 passed, 5 skipped, 45 subtests;
- Ruff: PASS;
- strict mypy: 147 source files, PASS;
- compileall and `git diff --check`: PASS;
- focused L1-A/B/C/D, backup, History/Today, startup, cancellation, scheduler,
  and distribution matrix: 317 passed, 3 skipped, 45 subtests;
- Library L1-D AppTests and signature checks under installed Streamlit 1.51.0:
  12 passed;
- isolated installed-wheel L1-D/provider/AppTests: 34 passed, 4 subtests.

The wheel used for that isolated check is 0.4.1 with schema 20 and config 5.
The fresh read-only Auditor returned PASS with no major or minor findings after
independently reproducing the boundary/timeout/environment repairs and rerunning
the cross-stage regression matrix. No real provider, network, PDF, or Atlas work
was performed during qualification.

An additional whole-repository AppTest run under Streamlit 1.51.0 exposed ten
pre-existing Today-page failures from its use of
`segmented_control(required=...)`; that API is outside the L1-D Library changes.
Every L1-D Library/AppTest and the L1-B callable-signature regression passes at
the declared floor, while the complete suite passes on the qualified installed
Streamlit 1.61.1. L1-D does not alter Today to conceal that independent baseline
compatibility issue.

The full disposable no-network/fake-provider smoke passed conversation creation,
Send, refresh persistence, deterministic compression, complete transcript
retention, explicit editable note promotion, and zero background calls. The
human requested only the hierarchy amendment above before freeze. The short
human re-smoke then passed the final Abstract, My Notes, AI Summary, AI
Discussions order; Abstract remained easy to read, notes remained editable and
durable, the prior transcript remained intact, and reload caused zero additional
provider calls. No persistence, provider, summary, retention, context, or schema
behavior changed. This completes human acceptance of the final Library L1
hierarchy and authorizes local L1-D freeze, but not push, tag, or release.
