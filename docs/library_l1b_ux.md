# Library L1-B attention-first UX

L1-B is a presentation and read-path substage over the frozen schema-19 L1-A
foundation. It adds no migration, persistent preview, copied prose, provider
binding, or model execution.

## Pre-change audit

The schema-19 data model was already suitable for the redesign, but the Library
page rendered every paper as a large bordered landing-page card. Each card
expanded source identity, three metrics, relevance context, notes, collections,
tags, generated connections, links, abstract controls, and save controls. In
addition to showing only one or two papers per typical desktop viewport, it
queried notes, collections, tags, and connections separately for every row and
constructed AI tag/connection generators merely to render their controls.

The old Library-page generation buttons conflict with L1-B's zero-AI invariant.
They are intentionally absent from the new page. Existing AI tags, summaries,
conversations, connection suggestions, collection intelligence, and provenance
remain stored. AI tags and stored relationship suggestions remain inspectable;
no stored state was deleted.

## Dense Library list

The existing `/library` route now renders one compact native Streamlit row per
paper with no card border. Each row contains:

1. explicit interest and reading state;
2. a tertiary title button that opens detail;
3. shared bounded author formatting and publication year;
4. at most two collection names and three provenance-aware tag labels, followed
   by `+N more`;
5. an optional deterministic one-line preview derived from the current note.

The row omits abstracts, summaries, full notes, relevance analysis, provider
metadata, transcript content, and action clusters. The control strip provides
local search plus interest, reading, collection, tag, and stable sort filters.
The default is recently saved. A small model-neutral session-state value retains
the filter selection while detail is open, so returning to the list restores the
working view without depending on Streamlit APIs newer than the declared 1.51.0
floor.

## Paper detail

Detail uses the same Streamlit page and a single `paper` query parameter rather
than a duplicate route. At the L1-B freeze, its fixed order was:

1. title, compact/full authors, publication/source identity;
2. interest, reading state, collections, and tags;
3. My Notes;
4. stored source abstract;
5. preferred AI summary resolved by the L1-A resolver, or an explicit empty
   state;
6. stored discussion overviews and an optional read-only transcript;
7. compact bibliography/source links;
8. a dormant Research Atlas placeholder.

Interest and reading use explicit dropdown text, including `Unrated` and `Not
set`, and persist immediately through the L1-A services. Collection and user-tag
multiselects update normalized relationships. AI tags are removal-only in L1-B,
so tag generation cannot be reached. Notes have separate read and edit surfaces.
No summary, conversation, context, connection, or tag generation control exists.

Stored related-paper suggestions remain available in a low-prominence expander
after the discussion section, but their generation control is absent. Collection
CRUD and existing deterministic collection intelligence remain lazily available
behind a native collection-manager toggle instead of expanding the paper list.

All Library controls use the intersection of the declared Streamlit 1.51.0 API
and the qualified installed API. Full-width title buttons use Streamlit's native
line wrapping; no unsupported wrapping keyword or custom CSS/HTML is required.

### Streamlit compatibility repair

The first real-browser smoke failed before freeze because the dense title button
passed an unsupported `wrap=False` keyword to `st.button`. The same unsupported
assumption appeared on three detail multiselects. The installed Streamlit 1.61.1
runtime and the declared minimum Streamlit 1.51.0 API accept no such keyword.
The minimum-version audit also found filter `persist_state` and modern expander
state arguments that were available in the installed runtime but not at the
declared floor.

The repair uses native button wrapping, ordinary session state for filter
restoration, and floor-compatible toggle/expander calls. A source-level
regression now binds every L1-B `st.*` keyword against the real installed
Streamlit signatures, rather than a permissive UI fake. The regression caught
an unsupported toggle keyword during the repair itself. Focused AppTests pass
under both Streamlit 1.61.1 and an isolated exact Streamlit 1.51.0 runtime.

## Query and storage behavior

List aggregation performs five reads independent of paper count:

1. saved Article/LibraryEntry rows;
2. latest relevance contexts in one window query for compatibility;
3. all saved-paper notes;
4. all saved-paper collection relationships;
5. all saved-paper tag relationships.

The page adds one collections-options query and one tags-options query, for seven
steady-state reads. Search adds one normalized, read-only SQLite query, for eight
page reads. Search no longer rebuilds the derived search document cache or fans
out per paper. The existing cache table remains untouched for compatibility.

Measured on synthetic normalized Libraries with a note, tag, and collection on
every paper (10 warm runs, median wall time):

| Saved papers | Aggregation reads | Search reads | List median | Search median |
|---:|---:|---:|---:|---:|
| 100 | 5 | 6 | 2.765 ms | 3.279 ms |
| 1,000 | 5 | 6 | 16.416 ms | 19.826 ms |

L1-B adds no table, column, index, durable UI state, note preview, rendered HTML,
summary copy, or tag/collection string copy. Schema remains 19 and config remains
5.

## Four-cost assessment

| Decision | Human attention | Local storage | AI tokens | Upgrade cost |
|---|---|---|---|---|
| Compact native rows | Several papers are visible where one large card previously dominated; the title and explicit user state lead | Preview and bounded labels are derived at render time | Zero | Rows consume `LibraryItem`, not provider records |
| Same-route detail | One title selection opens depth and Back restores filters | One transient query parameter; no durable copy | Zero | Uses existing navigation and L1-A services |
| Explicit state controls | Rating or reading state changes in one selection; NULL is never disguised | Updates only existing schema-19 columns | Zero | Values are the frozen L1-A enums/domains |
| Batched aggregation | Tags, collections, notes, and state arrive together without row-by-row waits | Reads normalized owners directly | Zero | UI is insulated from table layout by Library services |
| Source/user/AI hierarchy | Human judgment, notes, and abstract are encountered before derived interpretation | No content duplication | Zero | Summary display depends on the deterministic resolver |
| Read-only discussions | Existing local work can be inspected without presenting unavailable actions | Full L1-A transcript remains the sole copy | Zero | Provider/model provenance stays below the UI boundary |

## Human browser acceptance

The final human smoke passed on a disposable 24-paper schema-19 Library. The
human accepted the research-use density, primary title hierarchy, lightweight
interest/reading state, bounded secondary metadata, intuitive filters and detail
navigation, and passive presentation of existing AI summaries and discussions.
Rating, reading-state, and note edits persisted across refresh. The accepted
L1-B detail hierarchy was My Notes, Abstract, AI Summary, then AI Discussions;
the authoritative source abstract remained above and visually prior to derived
AI interpretation. Browsing and editing produced no visible model work, and
stored related-paper material remained secondary.

### Final L1 milestone hierarchy amendment

Final L1-D human validation intentionally superseded that original L1-B order.
The active paper-detail hierarchy is now Abstract, My Notes, AI Summary, then AI
Discussions. This human-approved amendment makes the progression authoritative
paper source, user interpretation/work, then AI-derived interpretation and
discussion. It changes presentation order only: the dense list, normalized note
store, summary/conversation services, zero-AI browsing invariant, and all L1-B
persistence/query semantics are unchanged.

## Freeze qualification

The final deterministic gate passed with 654 tests, 5 skips, and 37 subtests.
Ruff, strict mypy, compileall, and `git diff --check` passed. The focused current
Streamlit Library/AppTest/API matrix passed with 21 tests and 7 subtests; the
exact Streamlit 1.51.0 compatibility matrix passed with 13 tests. A real running
Streamlit server completed the `/library` protocol render with 24 paper buttons,
no exception element, and a successful script-finished status before the human
acceptance smoke.

The frozen L1-B contract retains schema 19, config 5, package 0.4.1, Recently
saved as the default sort, nullable user rating and reading state, zero-AI
Library navigation and edits, normalized L1-A persistence, bounded query count,
and no persistent UI convenience copies.

L1-C canonical ownership for new digest summaries and L1-D conversation execution
remain explicitly deferred. Research Atlas integration is not implemented.
