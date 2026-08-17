# M6 Campaign State

- campaign_state: M6_D_PLAN_FROZEN
- current_substage: M6-D Library search and scientific connections plan frozen; implementation not started
- current_branch: feature/m6-scientific-library-memory
- baseline_branch: master
- baseline_commit: fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b
- baseline_commit_subject: Prepare v0.2.0 release candidate
- latest_qualified_v0_2_code_state: fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b
- v0_2_qualified_tag: v0.2-rc-qualified
- v0_2_qualified_tag_object: 0a5ec71c000998144561f18aeb154ad65973af7e
- public_v0_2_0_tag: v0.2.0
- public_v0_2_0_tag_object: 209a7c2d47eb6a5af6c3613aef0137f0d3f9232f
- public_v0_2_0_tag_target: fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b
- local_origin_master_state: origin/master resolves to fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b
- online_remote_verification: `git ls-remote --heads --tags origin` failed with DNS resolution failure for `github.com` before and after network escalation.
- baseline_worktree_state: clean tracked worktree before M6 branch creation.
- package_version: 0.2.0
- runtime_version: 0.2.0
- baseline_schema_version: 8
- candidate_schema_version: 11
- config_version: 3
- codegraph_state: no `.codegraph/` directory exists at repository root.
- current_qualification_state: M6-C deterministic qualification and fresh read-only Auditor PASS; M6-D plan frozen.
- audit_round: M6-B audit repair round 1 PASS. M6-A initial candidate PASS; no M6-A audit-driven repair rounds used.
- deterministic_checks: final v0.2 freeze gate recorded `pytest` 262 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-A final gate recorded `pytest` 268 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-B candidate recorded `pytest` 283 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-B repair round 1 recorded `pytest` 284 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-C candidate recorded `pytest` 290 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS.
- live_checks: v0.2 live smoke was accepted by the human before the M6 branch. M6-B synthetic live Codex tag smoke reached the Codex CLI but exited non-zero with the sanitized authentication/usage-limits message; record as environment/provider limitation for later human live smoke, not deterministic code failure.
- schema_config_migration_state: v0.2 baseline uses ordered SQLite migrations through schema 8 and JSON config 3. M6-A adds additive SQLite schema 9 with `library_articles`; JSON config is unchanged. M6-B adds additive SQLite schema 10 for Library tags, tag assignments, and AI tag suppressions; JSON config is unchanged. M6-C adds additive SQLite schema 11 for article notes, collections/projects, and collection memberships; JSON config is unchanged. M6-D is expected to add additive SQLite schema 12 for rebuildable Library search documents, article relationship suggestions, and relationship dismissals; JSON config changes are not expected.
- qualified_local_commit: 7208191b3aa66c21863ec63d21e7d1f60ebe82b0
- qualified_local_tag: annotated local tag `m6c-qualified`; tag object `bef7ae04a957e539c5a977fc569621eee8d38311`; target `7208191b3aa66c21863ec63d21e7d1f60ebe82b0`. Prior local tags: `m6b-qualified` targets `104780a0ba9c98cd9663ef8d1088cb9472d53e09`; `m6a-qualified` targets `17e047c325bb61008cf39b9a135bea02bb63a968`.
- deferred_minor_optional_findings: M6-A Auditor noted Library save/remove UI lacks a dedicated Streamlit click smoke; deterministic service/helper coverage passed and this was classified MINOR/OPTIONAL. M6-B repair Auditor noted regeneration replacement is not a single DB transaction after provider success; current supported paths are covered, but a future atomic replace helper would be safer if the persistence path broadens. M6-C Auditor noted tag filter options may include tags retained only for AI suppression/tombstone history, which can yield no-result filter options.
- next_permitted_action: implement M6-D Library search and scientific connections according to the frozen plan below.
- human_stop_reason: none active

## Recovered v0.2 Baseline

- The latest qualified v0.2 code state is commit
  `fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b`.
- Local `master`, local `origin/master`, local branch
  `feature/v0.2-date-native-scheduler-ui`, local `v0.2-rc-qualified`, and
  local `v0.2.0` all resolve to that commit or to annotated tags targeting it.
- A public-style local `v0.2.0` tag exists and targets the complete qualified
  v0.2 product behavior.
- No qualified v0.2 RC repair remains uncommitted in the local worktree.
- M6 starts from a clean durable v0.2 baseline; no v0.2 freeze/commit repair is
  needed.

## M6 Campaign Charter

Purpose:

- Turn Research Digest from a daily information filter into a persistent
  scientific workspace.
- Support deliberate saved articles, user-created and AI-generated tags,
  personal notes, collections/projects, search/filtering, scientific
  relationships, and longitudinal scientific context.
- Keep the declared Interest Profile as the primary daily relevance authority.
  Library organization and long-term memory are additive layers, not
  replacements for M2 relevance.

Scope exclusions:

- M3 is not in scope: no RSS/general Atom feeds, arbitrary websites, journal
  APIs, HTML scraping, or additional source families.
- M5 is not in scope: no PDF/full-paper reading, section/equation extraction,
  or full-text scientific analysis.
- Do not introduce Redis, Celery, distributed services, authentication or
  multi-user infrastructure, cloud requirements, generic agent frameworks, or
  vector databases merely because M6 includes memory.
- SQLite remains the durable store unless real evidence proves it inadequate.

Supervised campaign model:

- Use a persistent Worker for implementation/repair substages.
- Launch a fresh independent read-only Auditor after each candidate.
- Default audit repair budget is initial candidate plus up to two
  audit-driven repair rounds per substage.
- Ordinary pre-audit implementation/test repairs do not count against the audit
  repair budget.
- Run deterministic qualification before each freeze.
- Use focused live UI/Codex smokes where behavior matters and the environment
  allows them.
- Commit locally and create local annotated qualification tags only after
  qualification.
- Do not weaken acceptance criteria to obtain PASS.

Human stop conditions:

- requirements are materially ambiguous;
- a frozen semantic contract would need to change;
- security/privacy boundaries must be weakened;
- new paid/external infrastructure, credentials, or authorization are required;
- data or repository integrity becomes ambiguous;
- Worker/Auditor evidence remains irreconcilable;
- bounded audit repair budget is exhausted;
- M6 final human gate is reached.

Data/privacy rules:

- Never record personal interest descriptions, paper contents, SQLite contents,
  API keys, Codex auth material, tokens, or local auth paths in campaign docs.
- Do not track `.env`, SQLite databases, virtualenvs, caches, Codex auth state,
  or local runtime state.
- Application code remains replaceable; user data survives independently.

## M6 Substage Outline

- M6-A: Saved Article Library. Suggested tag `m6a-qualified`.
- M6-B: AI tags and user tags. Suggested tag `m6b-qualified`.
- M6-C: Notes and collections/projects. Suggested tag `m6c-qualified`.
- M6-D: Library search and scientific connections. Suggested tag
  `m6d-qualified`.
- M6-E: Longitudinal scientific intelligence. Suggested tag `m6e-qualified`.
- M6-F: Upgrade and end-to-end qualification, then final human stop at
  `M6_RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN`.

## Frozen M6-A Plan

Goal: introduce a durable user-curated, article-centric Library.

Data model:

- Add additive SQLite schema version 9.
- Add a `library_articles` table keyed by `article_id` with:
  `article_id`, `saved_at`, `updated_at`, and an active saved-state marker.
- Use `articles.id` as the library identity bridge. The underlying stable
  cross-run identity remains `articles(source, source_article_id)`.
- Store save/unsave state outside run snapshots so historical digests remain
  immutable.
- Use `FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE` only
  for cleanup if an underlying Article is ever administratively deleted. Normal
  unsave must not delete the Article.
- Prefer soft state (`saved = 1/0`) over deleting the library row so re-save can
  preserve simple audit timestamps without duplicating state.

Domain/service boundary:

- Add small typed models such as `LibraryArticle` and `LibraryStatus` in
  `models.py` or a focused module if the existing model file gets noisy.
- Add database methods for save, unsave, status lookup, list saved articles,
  and bulk saved-state lookup by article ids.
- Add a focused service module, likely `research_digest.library`, that wraps
  DB operations for UI callers and keeps article-centric semantics explicit.
- Saving/unsaving must not call analyzers, mutate relevance analysis, mutate
  feedback, rerun pipeline work, or rewrite history snapshots.

UI integration:

- Add a Library navigation page through the existing `st.navigation` pattern.
- Add explicit save/unsave controls to normal paper cards where practical:
  Today analyzed items, Today preselected-out items, Today unresolved items if
  present, and History analyzed/preselected-out/unresolved snapshot cards.
- For Today cards, use live `Article.id` where available and call the Library
  service directly.
- For History snapshot cards, resolve by `source` plus `source_article_id`;
  if the Article exists, allow save/unsave. If a very old snapshot cannot be
  resolved to an Article, show a concise unavailable state rather than
  fabricating or backfilling risky data.
- Stable Streamlit widget keys must include source/article identity and UI
  context so toggling one paper does not affect another.
- The initial Library page should show title, authors, source/publication date,
  current available relevance context, saved date, arXiv/PDF links, Show
  abstract, and basic sorting/filtering.
- Current available relevance context should be best-effort from existing
  relevance analyses, not a historical snapshot rewrite. A practical first
  implementation can show the newest/highest available analysis context per
  saved article with profile/fingerprint metadata where available.

Behavioral contract:

- Saving is explicit user intent. Do not automatically save relevant papers.
- Repeated save is idempotent.
- Unsave removes the article from the Library view but does not delete the
  Article, digest history, run snapshots, relevance analyses, feedback,
  coverage, or scheduler state.
- Re-save restores saved state without duplicating the Article or Library row.
- The same Article appearing in multiple digest runs maps to one Library item.
- Library state is global single-user article curation in M6-A, not scoped to a
  run. Later substages may add tags, notes, and collections.

Tests required:

- DB migration from schema 8 creates the Library table and is idempotent.
- save, repeated save, unsave, re-save.
- same Article from multiple runs remains one Library item.
- saving a preselected-out Article.
- saving from History by source/article identity.
- unsaving preserves Articles, analyses, feedback, history snapshots, and
  app-run rows.
- Library listing includes expected article metadata, saved date, abstract, and
  available relevance context.
- basic Library sorting/filtering helpers.
- UI helper/state tests for save-button labels/keys and History unresolved
  article resolution where useful.
- v0.2 upgrade path includes Library table with no saved rows and preserves
  existing v0.2 data.

Deterministic qualification:

- focused tests for DB/library/UI helpers;
- full `pytest`;
- `ruff check src tests`;
- `mypy --strict src tests`;
- `python -m compileall src tests`;
- `git diff --check`;
- staged inventory/secret hygiene before freeze.

Live/smoke:

- Attempt a small Streamlit Library smoke if the environment can bind a socket.
- If socket/network restrictions recur, record them as environment limits and
  rely on deterministic Streamlit AppTest/helper coverage until human live
  smoke.

Audit/freeze:

- Launch a fresh independent read-only M6-A Auditor after candidate
  deterministic PASS.
- Repair BLOCKER/IMPORTANT findings within the bounded audit policy.
- After M6-A PASS, update these docs, commit locally, and create annotated tag
  `m6a-qualified`.

## M6-A Qualified Implementation Summary

- Added additive SQLite schema version 9 with `library_articles`, keyed by
  `article_id`, storing soft saved state plus saved/updated timestamps.
- Added typed Library entry and relevance-context models.
- Added `research_digest.library` as the service boundary for save, unsave,
  source-identity save, saved-state lookup, filtering, sorting, and best-effort
  current relevance context.
- Added a Library navigation page with search, sorting, title/authors/date
  metadata, current relevance context, arXiv/PDF links, original abstract
  display, and remove control.
- Added explicit save/remove controls to Today analyzed cards, Today
  preselected-out cards, Today analysis-unavailable cards, and History
  analyzed/preselected/unresolved cards when a stable source identity is
  available.
- Added Library membership to JSON backup export.
- Saving/removing Library membership does not call the analyzer, change
  relevance, change feedback, rerun pipeline work, or mutate historical run
  snapshots.

## M6-A Candidate Deterministic Evidence

- `pytest`: PASS, 268 passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

## M6-A Audit Evidence

- Fresh read-only Auditor: PASS.
- BLOCKER/IMPORTANT findings: none.
- Audit repair rounds used: 0.
- MINOR/OPTIONAL: dedicated Streamlit click smoke for save/remove controls may
  be added later; existing deterministic service/helper coverage passed.

## Frozen M6-B Plan

Goal: add durable user tags and AI-generated tags for saved Library articles,
with provenance and user override semantics.

Data model:

- Add additive SQLite schema version 10.
- Add `library_tags`:
  - `id`
  - `normalized_name` unique
  - `display_name`
  - `created_at`
  - `updated_at`
- Add `library_tag_assignments`:
  - `id`
  - `article_id`
  - `tag_id`
  - `origin` as `USER` or `AI`
  - `created_at`
  - `updated_at`
  - `ai_provenance_json` nullable for USER, required for AI
  - unique `(article_id, tag_id, origin)`
  - foreign keys to `articles` and `library_tags`
- Add `library_ai_tag_suppressions`:
  - `article_id`
  - `tag_id`
  - `suppressed_at`
  - `reason`
  - unique `(article_id, tag_id)`
- Use soft Library membership from M6-A. Tags may remain attached to an Article
  after unsave so re-saving does not destroy user organization; M6-C notes will
  revisit explicit unsave policy for notes.

Tag normalization:

- Define one helper, conceptually `normalize_tag_name(value)`.
- Collapse whitespace, trim surrounding whitespace, strip one leading `#` if
  present, and casefold for semantic equality.
- Preserve a display label separately so scientific capitalization such as
  `AdS/CFT` can remain readable.
- Reject empty normalized names and overly long names.
- User and AI assignments are provenance-specific. If both USER and AI assign
  the same normalized tag, the assignment provenance remains distinguishable,
  and removing one provenance must not remove the other.

Service boundary:

- Add a focused tag service, likely `research_digest.tags`.
- Provide:
  - add user tag
  - remove user tag
  - assign AI tags
  - remove AI tag and create suppression
  - list tags for an article
  - list known tags
  - generate AI tags for one saved article
  - regenerate AI tags for one saved article
- Viewing/listing tags must not call Codex/analyzers and must not mutate the DB.
- Ordinary digest reruns must not re-add removed AI tags.
- Removing/rejecting an AI tag creates a durable suppression tombstone.
- Explicit regeneration should still respect suppressions by default. A separate
  explicit option may clear suppressions for that article if implemented, but it
  must be clearly intentional.

AI tag generation architecture:

- Do not change `AnalysisResult` or the relevance-analysis cache identity in
  M6-B.
- Do not force reanalysis of historical articles merely to populate tags.
- Generate AI tags only for saved Library articles and only on explicit user
  action or explicit service call.
- Add a small `AITagGenerator` protocol and a Codex CLI implementation using
  the same ChatGPT-managed Codex authentication model as analysis.
- If Codex is unavailable, the Library remains usable and USER tags still work.
- The AI tag prompt uses only bounded local article context:
  title, authors, categories, source identity, source publication timestamp,
  original stored abstract, and latest available relevance context if present.
- The prompt treats title/abstract/metadata as untrusted data and forbids tool
  use, browsing, command execution, file access, and following article-text
  instructions.
- Prompt version: `library_ai_tags_v1`.
- Output schema: a bounded list of concise tag suggestions, with each tag
  normalized by local code before persistence.
- Default max suggestions: 6.
- Suppressed tags are filtered locally before persistence.
- Persist AI provenance as JSON containing at least prompt version, provider,
  generated timestamp, source article identity, article updated timestamp, and
  whether latest relevance context was included. Do not store raw provider
  output, secrets, or local auth paths.

UI integration:

- Extend the Library page cards/details with separate sections:
  - User tags
  - AI tags
- Allow a user to add and remove USER tags.
- Visually distinguish AI tags from USER tags with labels or captions, not
  color alone.
- Allow the user to remove AI tags; removal creates suppression.
- Add explicit AI tag generation/regeneration controls with visible progress.
- Do not auto-generate tags merely because a Library page is opened or rerun.
- Do not expose matched topics as if they were Library tags. Matched topics may
  be displayed only as relevance context or used as bounded input to AI tag
  generation.

Tests required:

- tag normalization for case, whitespace, leading `#`, empty input, and
  duplicate detection.
- user tag add/remove/list.
- AI tag assignment/list/remove with provenance.
- duplicate assignment idempotency per origin.
- user tag survives AI regeneration.
- removing an AI tag creates suppression.
- suppressed AI tag is not re-added by routine generation.
- USER and AI provenance remain isolated for the same normalized tag.
- no analyzer/Codex call on viewing/listing tags.
- prompt construction contains untrusted-data rules and bounded context.
- prompt injection text in title/abstract is treated as data.
- malformed, duplicate, unknown, empty, and oversized AI suggestions are
  rejected or normalized safely.
- schema 9 to 10 upgrade is deterministic and idempotent.
- backup JSON export includes tags, assignments, and suppressions without
  secrets.
- Library UI helper tests for label/key/state behavior.

Qualification:

- Focused M6-B tests.
- Full `pytest`.
- `ruff check src tests`.
- `mypy --strict src tests`.
- `python -m compileall src tests`.
- `git diff --check`.
- Fresh independent read-only M6-B Auditor.
- Small live Codex tag smoke where the environment and credentials allow it;
  otherwise record the environment limitation for human live smoke.
- After PASS, commit locally and create annotated local tag `m6b-qualified`.

## M6-B Audit Round 1 Finding

- IMPORTANT: AI tag regeneration removed existing AI assignments and optionally
  suppressions before the provider call succeeded. Provider failure could
  therefore delete local Library organization state. Required repair: generate
  and validate provider suggestions first, then replace assignments and/or clear
  suppressions only after successful generation; add regression coverage that
  failed regeneration preserves existing AI tags and suppressions.

Repair:

- Provider tag generation now happens before clearing suppressions or replacing
  existing AI assignments.
- Added regression coverage proving failed regeneration with
  `regenerate=True` and `clear_suppressions=True` preserves existing AI tags
  and AI tag suppressions.

Repair audit:

- Fresh read-only repair Auditor: PASS.
- BLOCKER/IMPORTANT findings: none remaining.
- Audit repair rounds used for M6-B: 1.
- MINOR/OPTIONAL: future broader replacement flows would benefit from a single
  atomic DB helper; current supported paths are covered by deterministic tests.

## Frozen M6-C Plan

Goal: turn saved Library papers into working material through personal notes and
lightweight collections/projects.

Data model:

- Add additive SQLite schema version 11.
- Add `library_article_notes`:
  - `article_id` primary key
  - `note_text`
  - `created_at`
  - `updated_at`
  - foreign key to `articles`
- Add `library_collections`:
  - `id`
  - `name`
  - `description`
  - `created_at`
  - `updated_at`
  - unique normalized name or equivalent deterministic duplicate prevention
- Add `library_collection_memberships`:
  - `collection_id`
  - `article_id`
  - `added_at`
  - unique `(collection_id, article_id)`
  - foreign keys to collections and articles
- Notes and collections attach to Article identity, not run snapshots.
- Notes and memberships may remain attached to an Article when it is unsaved,
  so re-saving does not destroy user work. The Library view may hide unsaved
  papers by default, but data must survive ordinary unsave/resave.

Note semantics:

- One editable personal note per Article for M6-C.
- Notes are local/private user-authored text.
- No Codex/analyzer call when viewing, editing, saving, or deleting notes.
- Notes must only mutate when the user explicitly saves/removes them.
- Notes must survive digest reruns, analysis reruns, tag generation, and
  unsave/resave.
- Empty note save should remove/clear the note row or store an empty note
  consistently; choose one behavior and test it. Preferred: empty/whitespace
  save deletes the note row.

Collection semantics:

- Collections/projects are lightweight named groupings, not a project
  management system.
- Collection names normalize with whitespace collapse and case-insensitive
  duplicate detection while preserving readable display text.
- A saved Article may belong to zero or more collections.
- Deleting a collection deletes memberships only, not Articles, analyses,
  notes, tags, history, or Library saved state.
- Renaming a collection preserves collection identity and memberships.
- Membership add/remove must be idempotent.

Service boundary:

- Add focused service helpers, likely `research_digest.collections`, for:
  - collection create/list/get/rename/delete
  - add/remove article membership
  - list article collections
  - list collection memberships
  - note get/save/delete
- Viewing/listing notes or collections must not call Codex/analyzers and must
  not mutate data.
- Search/filter integration should reuse local DB/service data.

UI integration:

- Extend the Library page with:
  - personal note editor per saved article, saved explicitly through a form
  - collection chips/list per article
  - add article to collection
  - remove article from collection
  - create collection with optional description
  - rename collection
  - delete collection with clear “papers are not deleted” copy
  - filters by collection and by existing Library tags
- Keep controls compact and native Streamlit-first.
- Do not invoke Codex from note or collection controls.
- Do not build a complex project-management UI.

Backup/export:

- JSON backup export must include notes, collections, and memberships.
- Do not export secrets or runtime paths.

Tests required:

- note save/update/delete.
- empty note clears note.
- notes survive digest reruns and analysis/tag operations.
- unsave/resave preserves notes.
- collection create/list/rename/delete.
- duplicate collection name normalization.
- membership add/remove idempotency.
- article in multiple collections.
- collection deletion preserves Articles, Library state, notes, tags, analyses,
  feedback, and history.
- Library filtering by collection.
- Library filtering by user/AI tags where available.
- viewing/listing notes/collections does not call analyzer/Codex and does not
  mutate DB.
- schema 10 to 11 upgrade is deterministic and idempotent.
- backup JSON export includes notes/collections/memberships.
- UI helper tests for collection/action keys and note form state where useful.

Qualification:

- Focused M6-C tests.
- Full `pytest`.
- `ruff check src tests`.
- `mypy --strict src tests`.
- `python -m compileall src tests`.
- `git diff --check`.
- Fresh independent read-only M6-C Auditor.
- After PASS, commit locally and create annotated local tag `m6c-qualified`.

## M6-C Audit Evidence

- Fresh read-only Auditor: PASS.
- BLOCKER/IMPORTANT findings: none.
- Audit repair rounds used: 0.
- MINOR/OPTIONAL: Library tag filter options may include tags retained only for
  AI suppression/tombstone history.

## Frozen M6-D Plan

Goal: make the saved Library searchable and persist bounded, provenance-bearing
scientific relationship suggestions among saved papers.

Search design:

- Add additive SQLite schema version 12.
- Add a rebuildable `library_search_documents` table keyed by `article_id`.
- Store derived search text fields from saved article metadata, tags,
  collection names/descriptions, abstract text, notes, and best-effort latest
  relevance context.
- Treat search documents as derived/rebuildable data. They must be updated by a
  focused service when Library metadata changes and can be rebuilt
  deterministically from normalized tables.
- Use SQLite-local search with normalized casefolded document text and bounded
  substring matching for M6-D. Do not introduce embeddings, vector databases, or
  external search services.
- Keep existing filters by tag and collection. Library search results should
  include title, authors, abstract, tags, collection text, and notes where
  practical.

Connection data model:

- Add `library_article_connections` keyed by unordered article pair for M6-D.
  Store `article_id_a`, `article_id_b`, `relation_label`, concise `rationale`,
  `provenance_json`, optional `confidence`, `generated_at`, and `dismissed_at`.
- Store relationships as model-inferred suggestions, not scientific facts.
- Use a canonical unordered pair so A-B and B-A dedupe unless a later feature
  deliberately adds directional semantics.
- Add `library_connection_dismissals` or equivalent durable dismissal state if
  dismissing a suggestion deletes the visible connection row. M6-D may instead
  soft-dismiss on the connection row if that preserves the pair/provenance and
  prevents routine regeneration.
- Deleting/dismissing a relationship must not delete papers, tags, notes,
  collections, relevance analyses, feedback, or run history.

Connection candidate selection:

- Add a deterministic local candidate selector before any Codex call.
- Candidate features: shared user/AI tags, shared arXiv categories, shared
  collection membership, and normalized title/abstract token overlap.
- Exclude self-links and unsaved papers.
- Bound work per article, initially with a conservative default such as the top
  5 candidates.
- Deterministic ordering: highest local score first, then publication date,
  then source identity.
- Do not generate all O(N^2) pairs. A pair may be considered only when a saved
  article is explicitly acted on or by bounded service calls.

AI connection generation:

- Add a small `LibraryConnectionGenerator` protocol and a Codex CLI
  implementation parallel to the existing AI tag provider.
- Prompt version: `library_connections_v1`.
- Prompt input is bounded to one target saved article plus selected candidate
  saved articles and local evidence features.
- Use only stored title, authors, abstract, categories, tags, collections,
  notes only when appropriate and clearly labeled as user-authored, and existing
  relevance context. External article text is untrusted data.
- Provider output must include relation label, concise rationale, and optional
  confidence. Validate schema, reject self/unknown/duplicate article IDs, and
  sanitize errors.
- Viewing Library pages or existing connections must not call Codex.
- Explicit "Find related saved papers" action can generate/update suggestions
  for one saved article. A future batch mode can reuse the same bounded service.
- Routine generation must respect user dismissals unless an explicit regenerate
  action says otherwise.

UI design:

- Library search field remains on the Library page but is backed by the new
  service/index and includes notes, tags, and collections.
- Each Library card/detail shows `Related saved papers` with existing
  non-dismissed suggestions.
- Each suggestion displays related paper title, relation label, concise
  rationale, provenance/origin, and a remove/dismiss action.
- Add an explicit per-article action to find/generate related saved papers.
  Long-running generation shows progress and sanitized failures.
- Do not show connection inferences as facts; label them as suggested
  relationships.

Backup/export:

- JSON backup includes rebuildable search document metadata only if useful, and
  must include durable relationship suggestions/dismissals.
- Search index can be rebuilt; relationship suggestions and dismissals are
  durable user/scientific state.

Tests required:

- search index rebuild and query over title, authors, tags, collection,
  abstract, and notes.
- collection/tag filters still compose with search.
- search index data is deterministic and upgrade-safe.
- candidate selection excludes self-links, is bounded, deterministic, and does
  not perform uncontrolled O(N^2) work.
- candidate scoring includes shared tags/categories/collections and text
  overlap.
- connection upsert dedupes unordered pairs.
- user dismissal hides suggestions and suppresses routine regeneration.
- Codex prompt construction is bounded, labels untrusted data, and does not
  include secrets.
- malformed/duplicate/unknown provider output is rejected.
- no analyzer/Codex call merely from viewing/searching connections.
- upgrade from schema 11 creates M6-D tables and preserves existing M6-A/B/C
  data.

Qualification:

- Focused deterministic tests for search, candidate selection, connection
  persistence, prompt parsing, UI helpers, and migration.
- Full `pytest`.
- `ruff check src tests`.
- `mypy --strict src tests`.
- `python -m compileall src tests`.
- `git diff --check`.
- Fresh independent read-only M6-D Auditor.
- Attempt a small live Codex connection-generation smoke if the environment can
  run Codex; otherwise record provider/environment limitation for human live
  smoke.
- After PASS, commit locally and create annotated local tag `m6d-qualified`.
