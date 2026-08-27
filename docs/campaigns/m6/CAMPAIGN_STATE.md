# M6 Campaign State

- campaign_state: POST_V0_3_INTEGRATED_REPAIR_QUALIFIED
- current_substage: Human-accepted coverage/cancellation/UI/author repairs qualified for the authorized local baseline commit
- current_branch: master
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
- package_version: 0.3.0
- runtime_version: 0.3.0
- baseline_schema_version: 8
- candidate_schema_version: 18
- config_version: 5
- codegraph_state: no `.codegraph/` directory exists at repository root.
- current_qualification_state: PASS. The post-v0.3 integrated repair candidate combines source-scoped durable coverage, detached local workers with true application cancellation, Today/Settings durable cancellation controls and reattachment, and ordered source-author presentation. Focused deterministic/AppTest qualification and fresh read-only audits passed for each repair. Human live smoke accepted coverage persistence, cancellation lifecycle, Today cancellation control, and author metadata presentation. The final integrated gate recorded `pytest -q` 447 passed and 9 subtests passed, explicit Streamlit AppTest suites 62 passed, migration/upgrade qualification 45 passed, `ruff check .` PASS, `mypy --strict src tests` PASS over 109 source files, `python -m compileall src tests` PASS, `git diff --check` PASS, wheel build PASS, isolated no-deps wheel install PASS, and installed CLI version/status/backup smoke PASS at schema 18/config 5.
- audit_round: Final integrated M6/v0.3 audit repair round 1 PASS. Final integrated Auditor initially found one IMPORTANT Settings Run-now preselector wiring issue; closure Auditor found no BLOCKER/IMPORTANT findings after repair. Final M6/v0.3 Stage-1 benchmark/default-effort focused Auditor PASS. Final M6/v0.3 stale-run recovery repair round 1 PASS. Final M6/v0.3 scheduler state repair initial candidate had one IMPORTANT CLI status fallback issue; repaired before focused closure Auditor, which then passed. Final M6/v0.3 startup side-effect repair round 1 PASS. Final M6/v0.3 refinement audit repair round 1 PASS after focused follow-up repairs. M6-F audit repair round 1 PASS. M6-E audit repair round 1 PASS. M6-D audit repair round 1 PASS. M6-B audit repair round 1 PASS. M6-A initial candidate PASS; no M6-A audit-driven repair rounds used.
- deterministic_checks: final v0.2 freeze gate recorded `pytest` 262 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-A final gate recorded `pytest` 268 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-B candidate recorded `pytest` 283 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-B repair round 1 recorded `pytest` 284 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-C candidate recorded `pytest` 290 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-D candidate recorded `pytest` 300 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-D repair round 1 recorded `pytest` 302 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-E candidate recorded `pytest` 310 passed after an implementation test repair, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-E repair round 1 recorded `pytest` 312 passed, `ruff check src tests` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, and `git diff --check` PASS. M6-F final repaired gate recorded `pytest` 315 passed, `ruff check .` PASS, `mypy --strict src tests` PASS, `python -m compileall src tests` PASS, `git diff --check` PASS, package wheel build PASS, isolated wheel install PASS, installed CLI `--version` PASS, installed CLI `status --json` PASS, installed CLI backup PASS, and Streamlit Library AppTest smoke PASS.
- live_checks: v0.2 live smoke was accepted by the human before the M6 branch. M6-B synthetic live Codex tag smoke reached the Codex CLI but exited non-zero with the sanitized authentication/usage-limits message; record as environment/provider limitation for later human live smoke, not deterministic code failure. M6-D synthetic live Codex connection smoke reached the Codex CLI but failed before model work because the CLI could not initialize in the read-only runtime; record as environment/provider limitation for later human live smoke, not deterministic code failure. M6-E synthetic live Codex context smoke reached the Codex CLI but failed before model work because the CLI could not initialize in the read-only runtime; record as environment/provider limitation for later human live smoke, not deterministic code failure. M6-F installed status smoke reported unsupported Windows Task Scheduler backend in this Linux/WSL sandbox; this is the expected environment limitation and not a scheduler code failure.
- schema_config_migration_state: v0.2 baseline uses ordered SQLite migrations through schema 8 and JSON config 3. M6-A adds additive SQLite schema 9 with `library_articles`; JSON config is unchanged. M6-B adds additive SQLite schema 10 for Library tags, tag assignments, and AI tag suppressions; JSON config is unchanged. M6-C adds additive SQLite schema 11 for article notes, collections/projects, and collection memberships; JSON config is unchanged. M6-D adds additive SQLite schema 12 for rebuildable Library search documents and article relationship suggestions with soft dismissal; JSON config is unchanged. M6-E adds additive SQLite schema 13 for per-new-paper Library context suggestions and collection intelligence snapshots; JSON config is unchanged. Final feedback refinement adds SQLite schema 14 for two-axis feedback and suggested interests plus JSON config 4 for the automatic Library-context threshold. Final cost/calibration/progress refinement adds SQLite schema 15 for quantitative relevance calibration and app-run progress, plus JSON config 5 for automatic Library connection enablement, model-effort/preselection fraction, and calibration prompt probability. Final model-based Stage-1 persistence advances SQLite schema to 16 with durable per-run preselection decisions. Post-v0.3 schema 17 migrates profile-scoped coverage into canonical source-scoped coverage and adds reusable source-date corpus manifests. Schema 18 additively records durable cancellation requests, exact run ownership, and run-owned provider process groups. Pre-migration backups and ordered upgrade behavior remain in force. JSON config remains 5.
- qualified_local_commit: final local commit tagged `m6f-qualified` after this document update.
- qualified_local_tag: annotated local tag `m6f-qualified` is the M6 release-candidate qualification tag. Prior local tags: `m6e-qualified` targets `fad6b8425bc14a956fb22f26f68cc485e46f71b9`; `m6d-qualified` targets `82c323d56c9ed9fbbdb8c36f602d03bd9d3d34b0`; `m6c-qualified` targets `7208191b3aa66c21863ec63d21e7d1f60ebe82b0`; `m6b-qualified` targets `104780a0ba9c98cd9663ef8d1088cb9472d53e09`; `m6a-qualified` targets `17e047c325bb61008cf39b9a135bea02bb63a968`.
- deferred_minor_optional_findings: M6-B repair Auditor noted regeneration replacement is not a single DB transaction after provider success; current supported paths are covered, but a future atomic replace helper would be safer if the persistence path broadens. M6-C Auditor noted tag filter options may include tags retained only for AI suppression/tombstone history, which can yield no-result filter options. M6-E repair Auditor noted context candidate eligibility can still spend prompt budget on a candidate whose only existing suggestion is collection-scoped and will later be skipped during assignment; no incorrect mutation occurs. M6 live Codex smokes require a runtime where Codex can initialize and authenticate; sandbox attempts reached the CLI but could not complete model work. The pre-existing import-order-sensitive `preselection`/`analysis.__init__` cycle is recorded with an exact reproduction in `docs/TECHNICAL_DEBT.md` and is explicitly deferred from this freeze.
- next_permitted_action: complete the authorized local integrated baseline commit. After that freeze, launcher work may begin as a separate scoped task. Do not push, tag, publish, or release without further human authority.
- human_stop_reason: final human release decision required after local freeze/version commit.

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

## Frozen M6-E Plan

Goal: use the saved Library to contextualize new digest papers and provide a
lightweight longitudinal view for collections/projects without redefining daily
relevance.

Core semantic decisions:

- The Interest Profile remains the authority for relevance scoring and
  preselection. Library memory adds context only.
- M6-E context statements are suggestions/inferences grounded in stored
  metadata, analyses, tags, collections, notes where explicitly local-only, and
  M6-D relationships.
- Do not send the entire Library to Codex. All prompt inputs must be bounded by
  deterministic local candidate selection.
- Do not introduce embeddings, vector databases, distributed services, or M5
  full-paper reading.
- Personal notes remain local/private by default. Do not send note text to
  Codex in M6-E prompts unless a later explicit user action authorizes it.
- Historical digest run snapshots remain immutable. New M6-E context is stored
  as additive records keyed to Article identity and run id where appropriate.

Data model:

- Add additive SQLite schema version 13.
- Add `library_context_suggestions` for new/analyzed digest articles:
  `id`, `run_id`, `article_id`, `related_article_id`, optional
  `collection_id`, `relation_label`, `rationale`, `origin`,
  `provenance_json`, optional `confidence`, `created_at`, `dismissed_at`.
- Canonicalize article pair meaning where only two papers are involved, but keep
  the new article/related saved article roles explicit for display.
- Add `collection_intelligence_snapshots` or a similarly focused table for
  lightweight collection/project summaries: `collection_id`, `title`,
  `summary`, `evidence_json`, `origin`, `provenance_json`, `generated_at`,
  optional `dismissed_at`.
- Dismissals must durably hide repeated suggestions without deleting papers,
  tags, notes, collections, M6-D connections, analyses, feedback, or history.

Deterministic candidate selection:

- For each newly analyzed article, select a bounded saved-Library context set
  using local evidence first:
  - shared Library tags / matched topics;
  - shared arXiv categories;
  - M6-D persisted relationships if the article is already saved;
  - Library search over title/abstract/tags/collections, excluding personal note
    text from Codex-facing evidence;
  - collection membership evidence for related saved papers.
- Bound context per new article, initially with conservative defaults such as
  top 5 saved papers and top 3 collections.
- Deterministic ordering: local score descending, then saved/recent publication
  recency, then source identity.
- Exclude self-links, unsaved articles, dismissed context suggestions, and
  candidates without meaningful local evidence.

AI context generation:

- Add a `LibraryContextGenerator` protocol and Codex CLI implementation with
  prompt version `library_context_v1`.
- Prompt input: one newly analyzed paper, its existing analysis result, bounded
  saved-paper candidates, collection labels/descriptions, tags, and local
  evidence. No personal notes. No full Library dump.
- Output: zero or more grounded context suggestions with related saved-paper id,
  optional collection id, concise relation label, rationale, optional
  confidence.
- Validate returned ids, reject duplicates/unknown/self links, sanitize provider
  errors, and persist only valid suggestions.
- Viewing stored context or opening Today/History/Library pages must not call
  Codex. Generation can happen explicitly after a digest run or through a
  bounded service hook if an analyzer/provider is available and tests prove it
  does not affect run success semantics.

Daily result UI:

- Add `Connections to your Library` beneath analyzed paper cards or as a
  compact section near synthesis.
- Clearly label each item as a suggested relationship and show the related
  saved paper/collection and rationale.
- Preserve existing Relevant, All analyzed, Below threshold, preselected-out,
  NEW/REUSED, synthesis, feedback, abstract, and Library controls.
- If no Library or no grounded context exists, show no noisy filler.
- Add dismiss controls for repeated suggestions with stable per-article keys.

Collection/project intelligence view:

- Add a lightweight section in the Library page under each collection or a
  dedicated collection detail expander.
- Show stored evidence-driven summaries such as recently connected papers,
  recurring tags/topics, recent additions, and suggested developments.
- Deterministic local summaries can be shown without Codex. Optional Codex
  collection intelligence generation is explicit, bounded, and uses prompt
  version `collection_intelligence_v1`.
- Do not present grand scientific conclusions. Use wording that distinguishes
  stored evidence from model inference.

Synthesis integration:

- Cross-paper synthesis may include a compact count/list of grounded Library
  connections for relevant papers, but relevance scores and matched_topics are
  unchanged.
- Do not mutate existing `AnalysisResult` or analysis cache identity merely to
  add Library context.

Backup/export:

- Export durable context suggestions, dismissals, and collection intelligence
  snapshots with article/collection identities.
- Do not export derived/rebuildable candidate scores unless needed as
  provenance evidence.

Tests required:

- bounded context candidate selection and deterministic ordering.
- no-library and no-connection behavior.
- no personal note text in Codex context prompts.
- prompt construction labels article metadata as untrusted data and remains
  bounded.
- provider output validation for duplicate/unknown/self ids.
- dismissed relation/context handling.
- collection isolation and collection-intelligence evidence.
- cache/reuse semantics: Library context does not change relevance-analysis
  cache keys and does not force reanalysis.
- historical run snapshots remain immutable.
- Today UI helper/state tests for context display and dismiss controls.
- upgrade from schema 12 creates M6-E tables and preserves M6-A/B/C/D data.

Qualification:

- Focused deterministic tests for candidate selection, persistence, prompts,
  provider parsing, UI helpers, backup, and migration.
- Full `pytest`.
- `ruff check src tests`.
- `mypy --strict src tests`.
- `python -m compileall src tests`.
- `git diff --check`.
- Fresh independent read-only M6-E Auditor.
- Attempt a small live Codex context-generation smoke if the environment can
  run Codex; otherwise record provider/environment limitation for human live
  smoke.
- After PASS, commit locally and create annotated local tag `m6e-qualified`.

## M6-F Upgrade and End-to-End Qualification

State:

- M6-F deterministic qualification is complete after one final audit-driven
  repair round.
- The release-candidate state is
  `M6_RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN`.
- No public push, public tag, package publication, or release creation has been
  performed.

Schema/config:

- Latest pre-M6 baseline: SQLite schema `8`, JSON config `3`.
- M6 release candidate: SQLite schema `13`, JSON config `3`.
- Schema migrations are additive:
  - schema 9: saved Library articles;
  - schema 10: Library tags, assignments, AI suppressions;
  - schema 11: notes, collections, memberships;
  - schema 12: derived Library search documents and article connections;
  - schema 13: Library context suggestions and collection intelligence
    snapshots.
- No new secret-bearing config fields were added.

Upgrade and preservation evidence:

- Deterministic release matrix covers fresh install, repeated startup,
  v0.1.0/M2-style upgrade, config upgrade, migration backups, user-data backup,
  packaging, installed editable CLI entry point, Codex unavailable, and network
  failure sanitization.
- Substage tests cover preservation and behavior for profiles, articles,
  analyses, feedback, synthesis/run history, coverage, scheduler config, saved
  Library entries, user tags, AI tags, AI suppressions, notes, collections,
  memberships, Library search/index, article connections, Library context, and
  collection intelligence.
- Article identity remains anchored on the existing `articles(source,
  source_article_id)` uniqueness contract and `articles.id` is the local
  Library identity bridge.
- Historical digest snapshots remain immutable.

Final deterministic checks:

- `pytest`: PASS, 315 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS via `python -m pip wheel . --no-deps`.
- Isolated wheel install: PASS.
- Installed CLI smoke: PASS for `research-digest --version`.
- Installed CLI fresh status smoke: PASS; schema 13/config 3/no last run.
- Installed backup smoke: PASS.
- Streamlit Library smoke: PASS through `streamlit.testing.v1.AppTest`.

Final audit:

- Fresh final read-only Auditor first found one IMPORTANT issue:
  `assign_connection_suggestions()` could persist a valid relationship before
  raising on a later invalid provider suggestion.
- Repair round 1 validates the full connection-provider batch before any
  connection persistence.
- Added regressions for valid-then-duplicate and valid-then-unknown batches
  leaving no persisted connections.
- Focused repair Auditor PASS; no BLOCKER/IMPORTANT findings remain.

Live checks:

- Human v0.2 live smoke was accepted before M6 began.
- M6-B/M6-D/M6-E synthetic Codex smokes reached the Codex CLI but could not
  complete model work in this sandbox because of provider/auth/runtime
  limitations. These are recorded as environment limitations, not deterministic
  code failures.
- Scheduler backend status in this Linux/WSL sandbox reports unsupported
  Windows Task Scheduler socket behavior; deterministic scheduler tests remain
  passing.

Release notes draft:

- Adds a user-curated saved Article Library.
- Adds explicit save/remove controls from Today and History paper cards.
- Adds Library page with sorting/filtering, relevance context, arXiv/PDF links,
  and original abstract display.
- Adds user tags, AI tags, AI provenance, and durable AI tag suppressions.
- Adds personal article notes and collections/projects.
- Adds local Library search over saved scientific material.
- Adds AI-suggested saved-paper connections with provenance and dismissal.
- Adds bounded Library context suggestions for new digest papers.
- Adds lightweight collection/project intelligence snapshots.

User guide draft:

- Use `Save to Library` on Today or History cards to deliberately keep a paper.
- Open `Library` to filter, sort, inspect abstracts, manage tags, edit notes,
  organize collections, and inspect related saved papers.
- Add user tags manually; use explicit AI tag generation only for saved papers
  when Codex is available.
- Removing an AI tag records a suppression so ordinary regeneration does not
  immediately re-add it.
- Collections group saved papers without owning or deleting them.
- Connections and Library context are suggestions with provenance, not
  scientific facts.

Privacy/data ownership notes:

- Library state, tags, suppressions, notes, collections, connections, and
  context are stored locally in SQLite.
- Personal notes are excluded from Codex-facing connection/context prompts.
- Viewing Library, tags, abstracts, notes, connections, or context does not call
  Codex.
- External article metadata and abstracts are rendered and passed to prompts as
  untrusted text.
- Backup exports M6 user data but not API keys, `.env`, Codex auth material,
  virtualenvs, caches, or runtime databases outside the active application DB.

Known limitations:

- arXiv remains the only source family.
- Analysis remains abstract-level; no PDF/full-paper reading.
- No RSS/journal/API expansion from M3.
- No vector database or embedding infrastructure.
- No multi-user/authentication infrastructure.
- AI tags, connections, and context require an available Codex runtime.
- M6 does not make automated scientific conclusions; it stores and presents
  bounded suggestions and local evidence.

Suggested next version:

- Use a post-0.2 feature version such as `0.3.0` for M6 if this is the next
  public feature release, or a project-specific milestone tag if version
  numbering is being decided separately.

Final human stop:

- Stop at this state for the human release decision.
- Suggested local qualification tag: `m6f-qualified`.
- Suggested public release tag target, if approved later: a human-approved
  release commit derived from `m6f-qualified` that sets the chosen public
  package/runtime version. The current qualification commit intentionally still
  reports package/runtime version `0.2.0` pending that release decision.

## Final RC Refinement - Feedback Semantics And Library-Context Cost Gate

State updated: 2026-08-18.

Current substage:

- `M6_FINAL_RC_REFINEMENT_QUALIFIED_AWAITING_HUMAN_LIVE_SMOKE`.

Baseline:

- Started from the qualified M6 RC commit `d58a3c75d05c8fc1548ae7b211a66a81de3a528a`
  (`m6f-qualified`) on branch `feature/m6-scientific-library-memory`.
- No public release/tag/push was performed by this refinement.

Implemented refinement scope:

- Replaced binary paper feedback in the Today paper-card UI with independent
  profile-fit and personal-interest questions.
- Stored feedback as nullable `profile_match` and `personal_interest` answers
  with explicit `YES`, `NO`, and `UNANSWERED` semantics.
- Preserved legacy binary `feedback_label` compatibility while moving profile
  calibration to the `profile_match` dimension only.
- Migrated legacy feedback deterministically:
  `RELEVANT -> profile_match YES, personal_interest NULL` and
  `NOT_RELEVANT -> profile_match NO, personal_interest NULL`.
- Added new-interest evidence queries for `profile_match NO` plus
  `personal_interest YES`.
- Added bounded deterministic Suggested Interests, explicit create/edit/dismiss
  UI, durable theme-level dismissal, and no automatic profile modification.
- Added config version `4` with
  `automatic_library_context_threshold = 0.90`.
- Wired automatic Library-context generation through Today/manual runs,
  Automation Run Now, CLI/headless automation, and the shared service path.
  Automatic expensive Library-context reasoning runs only for supplied
  generators, newly analyzed articles, and relevance scores at or above the
  configured threshold.
- Manual `Find Library connections` remains available below the threshold.
- JSON backup/export now includes suggested-interest profile records.

Schema/config migration state:

- SQLite schema advances from `13` to `14`.
- JSON config advances from `3` to `4`.
- Migrations are additive and idempotent in deterministic tests.
- Historical binary feedback remains preserved through compatibility
  `feedback_label`; personal-interest state is not guessed.

Deterministic qualification:

- `pytest`: PASS, 334 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS via `python -m pip wheel . --no-deps`.
- Isolated wheel install: PASS.
- Installed CLI `--version`: PASS, reports `research-digest 0.2.0`.
- Installed CLI `status --json`: PASS, initializes schema `14` and config `4`
  in isolated `/tmp` data/config.
- Installed CLI backup/export smoke: PASS.
- Streamlit AppTest coverage: PASS for two-question feedback controls,
  no default answers, persisted rerun state, explicit `UNANSWERED` clearing,
  abstract toggles, manual Library-connection action below threshold, and
  Settings threshold control.

Audit state:

- Fresh read-only refinement Auditor initially failed the candidate with one
  BLOCKER and three IMPORTANT findings:
  tri-state clearing was not persistable, suggestion dismissal was exact
  evidence-keyed rather than theme-keyed, suggestion construction was
  unbounded, and the automatic Library-context threshold was not wired into
  production paths.
- Repair round 1 closed those findings with explicit nullable clearing,
  theme-keyed suggestion suppression, bounded SQL evidence reads, and
  service/automation/UI threshold wiring.
- Fresh read-only repair Auditor PASS: no BLOCKER, IMPORTANT, or MINOR
  findings.

Focused human/live smoke checklist:

- Confirm a first-time user can understand and answer both feedback questions.
- Verify neither feedback question is preselected for an unanswered paper.
- Save each of the four combinations:
  profile yes/interest yes, profile yes/interest no,
  profile no/interest yes, profile no/interest no.
- Change and clear each answer independently using `Unanswered`.
- Confirm profile calibration follows only profile-fit answers.
- Mark at least three coherent outside-profile-but-interesting papers and
  inspect Suggested Interests.
- Dismiss a suggested interest, add another article in the same theme, and
  verify it does not reappear.
- Review and create a suggested profile only after explicit approval and edits.
- With about three saved Library papers and new digest scores below `0.90`,
  verify automatic Library-context Codex calls are zero.
- Verify a score at or above the configured threshold is eligible for automatic
  Library-context reasoning.
- Verify `Find Library connections` works manually below threshold.

Next permitted action:

- Return to human live smoke/review for this final refinement.
- Do not commit, tag, push, publish, or release without explicit human
  instruction.

## Final RC Refinement - Cost, Calibration, Scoring, And Progress

State updated: 2026-08-18.

Current substage:

- `M6_FINAL_RC_REFINEMENT_COST_CALIBRATION_PROGRESS_PACKAGE_PASS_AWAITING_AUDIT`.

Baseline:

- Continued from the uncommitted qualified M6/v0.3 refinement on
  `feature/m6-scientific-library-memory`.
- The underlying clean base remains `d58a3c75d05c8fc1548ae7b211a66a81de3a528a`
  (`m6f-qualified`).
- No commit, tag, push, package publication, public release, M3 work, or M5
  work has been performed.

Implemented refinement scope:

- Preserved the qualified two-axis feedback model:
  `profile_match` and `personal_interest`.
- Preserved Suggested Interests as evidence from
  `profile_match=NO` plus `personal_interest=YES`; quantitative human scores
  alone do not create new interests.
- Reaffirmed the preselected-out invariant: cache-miss papers that fail
  Stage-1 preselection do not receive new full relevance analysis, generated
  summary, why-it-matters, or Library-context reasoning for that run.
- Added user-facing Model effort under Settings -> Analysis, mapped to the
  existing internal `preselection_fraction` by
  `model_effort = 1 - preselection_fraction`.
- Added `automatic_library_connections_enabled`, default `true`. When disabled,
  digest-time automatic Library-context model calls are skipped while manual
  `Find Library connections` remains available.
- Preserved `automatic_library_context_threshold`, default `0.90`, and clarified
  that it gates extra model work for a new paper's final profile relevance
  score.
- Added quantitative human relevance calibration prompts with persisted
  one-time sampling decisions per completed digest run. Sampling defaults to
  `relevance_calibration_prompt_probability = 0.20`, creates at most one prompt
  per run, prefers newly analyzed below-threshold papers, excludes
  preselected-out/un-analyzed papers, and keeps model and human relevance scores
  separate.
- Saving an article to Library now records `personal_interest=YES` for the
  current profile context when available, without altering `profile_match`.
  Unsave does not set `personal_interest=NO`.
- Added a Settings Scoring Guide that documents relevance score, profile
  threshold, preselection score/threshold, Model effort mapping, automatic
  Library threshold, Library connection confidence, and human calibration score
  without claiming calibrated probabilities.
- Added low-frequency durable progress updates for long digest runs so
  `app_runs` counters and progress stage/message advance after retrieval,
  preselection, analysis batches, and terminal completion/failure.
- Backup/export now includes quantitative relevance calibration records.

Schema/config migration state:

- SQLite schema advances from `14` to `15`.
- JSON config advances from `4` to `5`.
- Additive database migration creates
  `quantitative_relevance_calibrations` and adds nullable `progress_stage` and
  `progress_message` fields to `app_runs`.
- Additive config migration adds:
  `automatic_library_connections_enabled`,
  `preselection_fraction`, and
  `relevance_calibration_prompt_probability`.
- Migrations preserve profiles, articles, analyses, two-axis feedback, Library
  state, tags, suppressions, notes, collections, connections, Suggested
  Interests, coverage, history, scheduler config, and backup/export behavior.

Deterministic qualification so far:

- `pytest`: PASS, 346 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS via `python -m pip wheel . --no-deps`.
- Dependency-resolving isolated wheel install: BLOCKED by environment DNS/PyPI
  access for declared dependencies, including `openai>=1.99.0`, even after the
  required network escalation retry.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`: PASS, reports `research-digest 0.2.0`.
- Installed CLI `status --json`: PASS, initializes schema `15` and config `5`
  in isolated `/tmp` data/config.
- Installed CLI backup/export smoke: PASS.

Audit state:

- Fresh independent closure Auditor remains pending for this final refinement.

Focused human/live smoke checklist:

- Confirm preselected-out papers show source metadata, original abstract, and
  Save to Library, without generated summaries or new full analysis.
- Save a Today analyzed paper, a Today preselected-out paper, and a History
  paper; verify `Personally interested` becomes `Yes` while profile match
  remains independent.
- Unsave a saved paper and verify personal-interest feedback is preserved.
- Inspect Settings -> Analysis Model effort at 100%, 50%, and 0%; verify
  displayed internal fraction and preselection threshold.
- Turn Automatic Library connections OFF and run a small digest with saved
  Library papers; verify automatic Library-context model calls are zero.
- Turn Automatic Library connections ON at threshold 0.90 and run below-threshold
  papers; verify automatic Library-context model calls are zero.
- Manually click `Find Library connections` for a below-threshold paper and
  verify one bounded explicit operation.
- Trigger a calibration prompt, submit one human 0..1 score, and verify the
  model score is only revealed after submission.
- Inspect Settings -> Scoring Guide.
- Run a multi-date digest and verify status/progress counters advance after
  retrieval, preselection, and analysis.

Next permitted action:

- Run a fresh independent Auditor.
- Return for human live smoke/review.
- Do not commit, tag, push, publish, or release without explicit human
  instruction.

## Final RC Refinement Repair Round 1

State updated: 2026-08-18.

Fresh closure Auditor findings:

- BLOCKER: none.
- IMPORTANT: stale/crashed run recovery left `progress_stage`/`progress_message`
  in the last nonterminal state.
- IMPORTANT: JSON backup/export omitted the new app-run progress fields.
- MINOR: top-level campaign-state header still reflected the earlier M6-F gate
  rather than schema `15` / config `5` refinement state.

Repairs:

- `_mark_unfinished_runs_failed` now sets terminal failed progress stage/message
  while marking stale unfinished runs failed.
- Backup/export `_runs` now exports `progress_stage` and `progress_message`.
- Campaign state header now reflects the current refinement, schema `15`, config
  `5`, and repair-round status.

Repair qualification:

- Focused regression tests: PASS, `pytest tests/test_run_lifecycle.py
  tests/test_backup.py tests/test_release_qualification_matrix.py -q`, 18
  passed.
- Full pytest: PASS, 346 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Repaired package build: PASS via `python -m pip wheel . --no-deps`.
- Repaired no-deps isolated wheel install: PASS.
- Repaired installed CLI `--version`: PASS, reports `research-digest 0.2.0`.
- Repaired installed CLI `status --json`: PASS, initializes schema `15` and
  config `5`.
- Repaired installed CLI backup/export smoke: PASS.
- Dependency-resolving isolated wheel install remains environment-blocked by
  DNS/PyPI access for declared dependencies, including `openai>=1.99.0`, as
  recorded above.

Focused repair Auditor:

- BLOCKER: none.
- IMPORTANT: top-level `schema_config_migration_state` still stopped at schema
  `13` / config unchanged despite the refinement now using schema `15` /
  config `5`.
- MINOR: backup export regression test asserted exported `progress_stage` but
  not exported `progress_message`.

Second repair:

- Top-level migration-state summary now includes schema `14` / config `4` from
  the feedback refinement and schema `15` / config `5` from the
  cost/calibration/progress refinement.
- Backup export regression test now asserts `progress_message` is exported.

Final repair qualification:

- Focused tests: PASS, `pytest tests/test_backup.py tests/test_release_docs.py
  -q`, 8 passed.
- Full pytest: PASS, 346 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Final package build: PASS via `python -m pip wheel . --no-deps`.
- Final no-deps isolated wheel install: PASS.
- Final installed CLI `--version`: PASS, reports `research-digest 0.2.0`.
- Final installed CLI `status --json`: PASS, initializes schema `15` and config
  `5`.
- Final installed CLI backup/export smoke: PASS.

Audit state:

- Fresh closure Auditor and focused repair Auditor findings have been addressed.
- Residual risks require human live smoke in the real Codex/browser/scheduler
  environment.

## Final RC Startup Side-Effect Repair

State updated: 2026-08-18.

Human live smoke found that `research-digest serve` appeared to start a
`Legacy digest`, leaving the UI unable to run an explicit digest because another
digest was already ongoing.

Deterministic root-cause trace:

- `research-digest serve`
  -> `research_digest.cli._serve_command`
  -> launches `streamlit run src/research_digest/ui/app.py`.
- Streamlit default page:
  -> `research_digest.ui.app.main`
  -> `today.render`
  -> `_render_date_selection_control`
  -> `resolve_latest_available_source_date`
  -> `ArxivSource.resolve_latest_available_date`
  -> arXiv `_fetch_page`.
- Settings/Automation page:
  -> `_render_coverage_overview`
  -> `build_automatic_coverage_plan`
  -> `ArxivSource.resolve_latest_available_date`
  -> arXiv `_fetch_page`.
- Today page also constructed the analyzer and automatic Library-context
  generator before the explicit `Run digest` click.

Deterministic inspection found no supported UI startup path that directly calls
`run_digest_for_profile`, `run_automatic_digest_now`, or acquires the run lock.
The repair nevertheless enforces this boundary with AppTest coverage that fails
on any startup-time source fetch, provider construction, run-service call, or
`app_runs` insertion, and verifies the digest run lock remains free after
startup render.

Repair:

- Today/latest-available mode no longer resolves the latest source date during
  page render. It preserves `DateSelection.latest_available()` and resolves it
  only inside the explicit run service after `Run digest`.
- Today no longer builds the analyzer or automatic Library-context generator
  during page render. Both are constructed only inside the explicit `Run digest`
  path.
- Settings/Automation no longer resolves latest available or pending catch-up
  dates during page render. The overview is DB-only on load and states that
  pending dates are checked when `Run now` starts.
- `Run now` still computes pending dates and uses the shared automation service
  only after the explicit button click.
- Suggested Interests generation is no longer run during Settings render.
  Settings lists stored suggestions read-only and generates/refetches
  suggestions only after an explicit `Refresh suggested interests` click.
- Manual `Find Library connections` no longer constructs the Library-context
  generator during article-card render; generator construction and provider
  checks happen only after the explicit button click.
- History renders legacy-format rows as historical data only.

Regression tests:

- `tests/test_streamlit_startup_side_effects.py` verifies Today initial load,
  Today refresh/rerun, Settings initial load, legacy History/Today display, run
  lock freedom after startup render, and exactly-one service invocation after a
  single `Run digest` click.
- It also verifies Settings render does not refresh/create Suggested Interests
  even when qualifying new-interest evidence exists.

Startup repair deterministic qualification:

- Focused startup tests: PASS, 6 passed.
- Affected regression set: PASS, 76 passed.
- Full `pytest`: PASS, 351 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `python -m pip wheel . --no-deps`.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`: PASS, reports `research-digest 0.2.0`.
- Installed CLI `status --json`: PASS, schema `15`, config `5`.
- Installed CLI backup smoke: PASS.

Focused Auditor:

- Initial focused Auditor found no BLOCKER issues and one IMPORTANT issue:
  Settings render called `refresh_suggested_interests`, which could mutate
  stored `suggested_interest_profiles` during ordinary page load when enough
  new-interest evidence existed.
- Repair round 1 moved Suggested Interests generation behind explicit refresh
  and deferred manual Library-context generator construction until explicit
  `Find Library connections`.
- Focused repair Auditor found no BLOCKER or IMPORTANT findings.
- MINOR/OPTIONAL: add an extra AppTest around existing result-card render to
  prove manual Library-context generator construction remains deferred until
  `Find Library connections`. Code inspection confirms the behavior; this is not
  a release blocker.

## Final RC Scheduler State Repair

State updated: 2026-08-18.

Human live smoke found Windows Task Scheduler reported:

- Task name: `Research Digest Daily`
- State: `Ready`
- Last run: `2026-08-18 06:00:01`
- Last task result: `3221225786`
- Next run: `2026-08-19 06:00:00`

Settings incorrectly rendered `Automatic daily digest = OFF` because scheduler
inspection failed while converting the nonzero previous execution result to
`System.Int32`.

Root cause:

- `_status_script` cast `$info.LastTaskResult` to `[int]`, which can overflow
  for Windows task result codes such as `3221225786`.
- Settings used `bool(status.schedule and status.schedule.installed)` for the
  automation toggle, so any status inspection/parsing failure collapsed to an
  OFF-looking toggle.

Repair:

- Windows status inspection now emits `[int64]$info.LastTaskResult`.
- Settings uses explicit tri-state schedule interpretation:
  - enabled: task installed and state is not `Disabled`;
  - disabled: task missing or task state is `Disabled`;
  - unknown: scheduler status inspection failed or no status object is
    available.
- A nonzero `LastTaskResult` is displayed as a previous-run warning only; it no
  longer changes whether the schedule is shown as enabled.
- Unknown scheduler status renders `Schedule state unavailable` and does not
  render an OFF `Automatic daily digest` toggle. Schedule mutation controls are
  disabled until inspection succeeds.
- CLI status now preserves unknown scheduler state as `status_available=false`
  and `installed=null` in JSON, and human-readable status says `Schedule:
  status unavailable` instead of `installed=False`.
- `Run now` remains an explicit separate operation.

Regression tests:

- `tests/test_scheduler.py` verifies large Windows task result parsing and that
  the PowerShell status script uses `[int64]`.
- `tests/test_settings_page.py` verifies enabled/disabled/unknown schedule
  state interpretation, including Ready with result `3221225786`.
- `tests/test_settings_ui_smoke.py` verifies Settings renders:
  - Ready/result `0` as Automatic daily digest ON;
  - Ready/result `3221225786` as ON with next run visible and prior-run warning;
  - Disabled as OFF;
  - status parsing failure as unavailable without an OFF toggle.
- `tests/test_cli.py` verifies scheduler inspection failure is reported as an
  unknown scheduler state in JSON and human output, never as installed/off
  false.

Scheduler-state repair deterministic qualification:

- Focused scheduler/CLI/settings tests: PASS, 42 passed and 6 subtests passed.
- Full `pytest`: PASS, 361 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `python -m pip wheel . --no-deps`.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`: PASS, reports `research-digest 0.2.0`.
- Installed CLI `status --json`: PASS, schema `15`, config `5`. In this
  sandbox, scheduler inspection is unavailable and the installed CLI reports
  `status_available=false` with `installed=null`, which is the intended cautious
  fallback.
- Installed CLI backup smoke: PASS.

Focused Auditor:

- PASS.
- BLOCKER: none.
- IMPORTANT: none.
- MINOR/OPTIONAL: none.
- Auditor verification: `python -m pytest tests/test_scheduler.py
  tests/test_settings_page.py tests/test_settings_ui_smoke.py
  tests/test_cli.py tests/test_cli_schedule.py tests/test_automation.py` PASS,
  52 passed.

## Final RC Stale Run Recovery Repair

State updated: 2026-08-18.

Human live smoke confirmed run `#43` was created by the scheduled 06:00
execution and remained `RUNNING` after Windows Task Scheduler reported the task
process had ended with `0xC000013A` / `3221225786`.

Live read-only state before repair:

- Last run: `#43`, status `RUNNING`, origin `SCHEDULED`.
- Counts: retrieved `198`, stored `58`, preselected `177`, skipped `21`,
  analyzed `70`, relevant `0`.
- Progress: `analysis`; message `Full analysis 70 / 177; Codex batch 15 / 36
  (size 5).`
- Durable run lock: `name=digest`, owner `pid:<legacy uuid>`, acquired
  `2026-08-18T11:00:02.059131Z`.
- The old owner string did not contain an actual PID or process start identity,
  so process liveness could not be inspected. Repaired `status --json` now
  reports this as `run_lock.owner_state = "unknown"`.

Root cause:

- Existing run-lock recovery was age-only. A dead owner process could block a
  new explicit run until the six-hour stale threshold elapsed.
- The lock owner string looked process-related but stored only a UUID, not a
  PID, host, or process start identity.
- `KeyboardInterrupt`/`SystemExit` could bypass pipeline finalization because
  only ordinary `Exception` was caught.

Repair:

- New run-lock owners are process-aware JSON strings containing PID, host,
  Linux `/proc/<pid>/stat` start ticks, and a nonce.
- Lock acquisition now preserves overlap exclusion for owners that are
  inspectably alive.
- Lock acquisition immediately recovers inspectably dead owners, marks the
  abandoned unfinished run terminal `FAILED`, preserves existing progress
  counts, deletes stale ownership, and then acquires the new lock.
- PID reuse is treated as dead when the recorded process start ticks differ
  from the current process at that PID.
- Unknown/uninspectable owners still obey the existing age-based stale cutoff
  during automatic lock acquisition.
- Added explicit app-level recovery command:
  `research-digest recover-abandoned-run --run-id <ID>`.
- For legacy/uninspectable owners, the command refuses to recover unless
  `--force-uninspectable-owner` is provided after the human confirms no digest
  owner process is alive.
- CLI `status --json` now includes `run_lock` with owner state so recovery can
  be inspected without SQLite editing.
- Catchable interruptions now finalize the current run as `FAILED` with a
  sanitized interrupted message and release ownership through existing
  `finally` blocks.

Regression tests:

- `tests/test_run_locks.py` covers process-owner liveness, missing process,
  PID reuse, legacy unknown owner, and cross-host unknown owner.
- `tests/test_run_lifecycle.py` covers active owner blocking, dead-owner
  recovery before age staleness, legacy owner forced recovery, interrupted
  scheduled-run recovery preserving History/counts, retry after recovery
  reusing valid analyses, catchable `KeyboardInterrupt` finalization, and
  catchable interruption after a successful analysis chunk preserving the
  durable analyzed count.
- `tests/test_cli.py` covers `run_lock` status output and explicit
  `recover-abandoned-run` behavior with and without the legacy-owner force flag.
- Scheduler enabled/disabled/unknown repair tests remain passing.

Deterministic qualification:

- Focused stale-run/scheduler/CLI tests after repair round 1: PASS, 61 passed
  and 6 subtests passed.
- Full `pytest`: PASS, 376 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `python -m pip wheel . --no-deps`.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`: PASS, reports `research-digest 0.2.0`.
- Installed CLI `status --json`: PASS, schema `15`, config `5`, `run_lock`
  field present.
- Installed CLI backup smoke: PASS.

Pending:

- Human live recovery smoke for run `#43`; no manual DB editing.

Audit round 1:

- Initial stale-run recovery Auditor found one IMPORTANT issue: catchable
  interruption during full-analysis batching could overwrite already persisted
  partial analysis progress with stale in-memory counters.
- Repair: interruption finalization now reads the current durable run counters
  and uses the maximum of durable and in-memory values before marking the run
  terminal.
- Added regression test for interruption after one successful analysis chunk;
  the terminal failed run preserves `analyzed_count`.
- MINOR/OPTIONAL boot-id strengthening was also implemented: new process-owner
  records include Linux boot ID where available, reducing reboot/PID/start-tick
  ambiguity.

Focused closure Auditor:

- PASS.
- BLOCKER: none.
- IMPORTANT: none.
- MINOR/OPTIONAL: add a direct boot-ID mismatch test for the optional
  hardening branch. The implementation was inspected and no release-blocking
  issue remains.

## v0.3 RC Preselection Calibration Repair

State timestamp: 2026-08-18T15:38:19Z.

Current HEAD before freeze: `d58a3c75d05c8fc1548ae7b211a66a81de3a528a`.

Human live diagnostic for run `#46` established:

- Model effort `30%`.
- `preselection_fraction = 0.70`.
- profile relevance threshold `0.70`.
- preselection threshold `0.49`.
- run accounting was correct: 31 retrieved, 5 reused, 26 screened, 21 passed
  preselection, 5 preselected out, 21 new analyses, 26 total analyzed, 2
  relevant.
- every newly analyzed paper passed the Stage-1 gate, so the defect is
  preselection-score calibration drift, not threshold-enforcement failure.

Repair candidate:

- Production Today and Automation/Run Now paths now build provider-backed
  abstract preselectors through the configured analyzer provider.
- Codex provider uses `CodexAbstractPreselector`.
- OpenAI provider uses `OpenAIAbstractPreselector`.
- `TermOverlapPreselector` remains available for deterministic tests/offline
  fallback only and is no longer the ordinary production scientific
  preselector.
- Stage-1 prompt freezes the abstract-level question:
  "From the title and abstract alone, how plausible is it that a deeper
  relevance analysis would find this paper meaningfully relevant to the
  selected Interest Profile?"
- Stage-1 output is minimal: article id and `preselection_score` only.
- Rubric is ordinal, not probabilistic:
  0.00-0.19 no substantive plausible connection; 0.20-0.39 weak/general
  adjacency; 0.40-0.59 plausible indirect connection; 0.60-0.79 strong
  plausible relevance; 0.80-1.00 direct/core apparent match.
- Bounded preselection chunks use default chunk size 20 with retry chunk sizes
  20, 10, 1.
- Missing/malformed/duplicate/unknown IDs are rejected and only unresolved IDs
  are retried.
- Stage-1 provider failure is explicit fail-open: affected papers receive full
  analysis if the full analyzer remains available, with decision origin
  `UNAVAILABLE_FAIL_OPEN`.
- Rejected papers still receive no full relevance analysis, generated summary,
  why-it-matters text, reading priority, or automatic Library context.
- Cached valid full analyses still bypass Stage 1 and are recorded with origin
  `REUSED_ANALYSIS_BYPASS`.

Schema/config state:

- Database schema bumped from 15 to 16.
- Added additive table `preselection_decisions`.
- No config-version bump required.
- Preselection evidence records run id, article id, profile/source semantic
  fingerprints, score, threshold, pass/reject, origin, stage, preselector
  version, optional sanitized/internal reason, and creation time.
- Run snapshots now include `preselection_decisions`.
- JSON export includes `preselection_decisions`.

Deterministic qualification:

- `pytest -q`: PASS, 389 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build smoke: PASS via `pip wheel . --no-deps --wheel-dir
  /tmp/research-digest-wheel`.
- Isolated no-deps wheel install smoke: PASS.
- Installed CLI `research-digest --help`: PASS.

Run `#46` benchmark state:

- Read-only reconstruction found the live default DB at
  `/home/inaeyk/.local/share/research-digest/research_digest.sqlite3`, schema
  15, with run `#46` and its immutable snapshot.
- The 26 originally screened papers were reconstructed as 21 `NEW_THIS_RUN`
  analyzed papers plus 5 preselected-out papers.
- A sandboxed Codex preselection attempt failed before model execution because
  Codex could not initialize its app-server client on the read-only filesystem.
- An outside-sandbox benchmark was not run: the approval request was rejected
  because it would send private article abstracts from the local database to
  Codex/LLM without explicit human authorization for that payload.
- Next permitted action: human may explicitly authorize the live run `#46`
  Stage-1 benchmark, or perform it manually using the repaired code.

Qualification state:

- Deterministic candidate: PASS.
- Live Codex run `#46` benchmark: BLOCKED pending explicit human approval.
- Fresh focused Auditor: in progress.
- Do not commit, tag, push, publish, or freeze v0.3 yet.

Audit repair round 1:

- Initial focused Auditor found one BLOCKER and one IMPORTANT issue.
- BLOCKER: deterministic CLI/Automation tests that injected `FakeAnalyzer`
  could still construct the real provider-backed Codex preselector and invoke
  live Codex Stage 1.
- Repair: `run_automatic_digest_now` and the CLI test seam now accept an
  explicit `AbstractPreselector`. Deterministic tests inject a fail-open fake
  preselector; production callers that omit the parameter still use
  `build_configured_preselector`.
- IMPORTANT: scheduled runs could lose UI-saved M6 analysis settings when a
  custom config directory was in use.
- Repair: scheduled environment now includes `RESEARCH_DIGEST_CONFIG_DIR`
  alongside `RESEARCH_DIGEST_DB` and provider settings. Scheduler tests assert
  the value is included and secrets remain excluded.

Post-repair deterministic qualification:

- `pytest -q`: PASS, 389 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build smoke: PASS via `pip wheel . --no-deps --wheel-dir
  /tmp/research-digest-wheel-2`.
- Isolated no-deps wheel install smoke: PASS.
- Installed CLI `research-digest --help`: PASS.

Focused closure Auditor:

- In progress.

Current next permitted action:

- Wait for closure Auditor.
- If PASS, return to human review for explicit live Codex benchmark authorization
  or human-run benchmark/live smoke.

Audit repair round 2:

- Closure Auditor found one remaining IMPORTANT issue: direct calls to
  `run_automatic_digest_now` with an injected fake analyzer but no injected
  preselector could still build a configured Codex preselector.
- Repair: `run_automatic_digest_now` now treats an injected analyzer with no
  explicit preselector as a deterministic/test seam and uses
  `UnavailableFailOpenPreselector` unless `use_configured_preselector=True` is
  explicitly supplied.
- Production CLI calls pass `use_configured_preselector=True`; installed CLI
  and ordinary UI/Automation behavior still use provider-backed model
  preselection by default.
- Added direct Automation regression proving injected fake analyzer with no
  preselector does not build the configured/live preselector.

Final deterministic qualification after repair round 2:

- `pytest -q`: PASS, 391 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build smoke: PASS via `pip wheel . --no-deps --wheel-dir
  /tmp/research-digest-wheel-4`.
- Isolated no-deps wheel install smoke: PASS.
- Installed CLI `research-digest --help`: PASS.

Current qualification state:

- Deterministic repair candidate: PASS.
- Audit repair budget used: initial candidate + 2 audit-driven repair rounds.
- Final focused closure Auditor: PASS, 38 focused tests passed in auditor run.
- Remaining human stop: live Codex run `#46` benchmark/live smoke requires
  explicit human authorization because it sends local article abstracts to the
  model provider.
- Do not commit, tag, push, publish, or freeze v0.3 until human review.

## Run #46 Live Benchmark Attempt

State timestamp: 2026-08-18T16:14:27Z.

Human authorized a read-only live Codex benchmark using the 26 saved run `#46`
title/abstract records that originally required Stage-1 screening.

Execution constraints:

- SQLite was opened read-only.
- No run `#46`, article, analysis, feedback, coverage, or Library records were
  modified.
- The benchmark used `CodexAbstractPreselector` with profile threshold `0.70`,
  preselection fraction `0.70`, and cutoff `0.49`.
- Known final relevance scores were not included in the Stage-1 prompt.

Outcome:

- Codex did not reach model execution.
- `codex exec --ephemeral --sandbox read-only` failed during in-process
  app-server initialization with a read-only filesystem error.
- All 26 articles therefore received explicit `UNAVAILABLE_FAIL_OPEN`
  preselection decisions.
- New Stage-1 score distribution is unavailable.
- Scientific benchmark metrics that require Stage-1 scores are undefined.
- Fail-open behavior preserved the primary scientific safety property: no
  known relevant article was rejected, but no full-analysis work would be
  avoided under this failed-provider condition.

Run `#46` fail-open aggregate:

- total screened: 26.
- passed via fail-open: 26.
- rejected: 0.
- known final relevance scores available: 21.
- median known final relevance: 0.22.
- known final `<= 0.20`: 10, all fail-open/pass.
- known final `>= 0.70`: 1, fail-open/pass.
- estimated full-analysis calls avoided versus old run `#46`: 0.

Live new-paper smoke:

- arXiv source-only smoke was attempted in the sandbox and outside the sandbox.
- Both attempts failed DNS resolution for the arXiv API.
- No disposable live digest could be completed in this environment.

Current next permitted action:

- Human live environment should repair/verify Codex CLI app-server state and
  network/DNS, then rerun the benchmark/live smoke.
- Do not release/freeze v0.3 based on this local live benchmark; it did not
  produce model scores.

## Human-Run Run #46 Stage-1 Benchmark

Human subsequently ran the read-only benchmark from an ordinary WSL shell.

Scientific result:

- total screened: 26.
- passed at Model effort 30%: 3.
- rejected at Model effort 30%: 23.
- pass rate at 30%: 11.5%.
- Spearman Stage-1 vs final relevance: approximately 0.87.
- all 10 papers with historical final relevance `<= 0.20` were rejected.
- one known genuinely relevant paper was incorrectly rejected at 30% effort:
  Stage-1 score `0.46`, historical final relevance `0.74`.
- At relevance threshold `0.70`, 30% Model effort means preselection fraction
  `0.70` and cutoff `0.49`.
- The false negative was fifth-highest by Stage-1 score and only `0.03` below
  the cutoff.

Product refinement:

- Stage-1 prompt/rubric remains unchanged.
- Default Model effort for new/default configuration changes to 40%.
- Default `preselection_fraction` changes to `0.60`, giving cutoff `0.42` at
  relevance threshold `0.70`.
- Existing explicitly saved user values are not overwritten.
- Projected run `#46` behavior at 40% effort: 5/26 pass; the known relevant
  paper is preserved; all known final `<= 0.20` papers remain rejected; 16 full
  analyses avoided versus the old lexical preselector.

Qualification:

- `pytest -q`: PASS, 392 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS, 100 source files checked.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package wheel build with `python -m pip wheel . --no-deps`: PASS.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --version`: PASS, reports
  `research-digest 0.2.0`.
- Fresh focused read-only Auditor PASS: no BLOCKER or IMPORTANT findings.

Next permitted action:

- Return for final human smoke of the 40% default Model effort refinement.
- Do not commit, tag, push, publish, or release before human approval.

## Final Integrated M6/v0.3 Feature Freeze

State timestamp: 2026-08-18.

Human live smoke:

- PASS for Settings -> Model effort worked example.
- PASS for dynamic use of relevance threshold, Model effort, and derived
  Stage-1 cutoff.
- PASS for updating the example after Model effort / relevance threshold
  changes.
- PASS for minimal Today and History preselected-out cards:
  metadata, preselected-out state, arXiv/PDF, Show abstract, and Save to
  Library, with no generated summary/relevance reason/priority/why-it-matters.
- PASS for source abstract display with no analysis side effects.
- PASS for previously accepted two-axis feedback, quantitative calibration,
  automatic Library toggle/threshold, Model effort control, Scoring Guide,
  Suggested Interests, Library/tags/notes/collections/connections, stale-run
  recovery, and scheduler repairs.

Final feature-candidate deterministic/package gate:

- `pytest -q`: PASS, 393 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS, 100 source files checked.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Wheel build: PASS, generated
  `research_digest-0.2.0-py3-none-any.whl` before release-version bump.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --version`: PASS, reported
  `research-digest 0.2.0` before release-version bump.
- Installed CLI `status --json`: PASS with isolated data/config, initialized
  SQLite schema `16` and JSON config `5`; Windows scheduler status was
  unavailable in the Linux/WSL sandbox with a sanitized WSL socket message.
- Streamlit AppTest smoke: PASS, 17 passed.

Freeze actions authorized by human:

- Stage and commit the complete qualified feature state locally.
- Create/update the local M6 qualification tag.
- Create a separate minimal local v0.3.0 release-version commit.
- Re-run release checks after the version bump.
- Do not push, publish, create a public v0.3.0 tag, or create a public release.

Local freeze record:

- Qualified feature commit: `3383ab360d5af0fb17263204863e7bfd5f284ac1`.
- Local qualification tag: `m6-v0.3-qualified`, targeting the qualified
  feature commit.

## v0.3.0 Release-Version Commit

Scope:

- Bump package metadata in `pyproject.toml` from `0.2.0` to `0.3.0`.
- Bump runtime `research_digest.__version__` from `0.2.0` to `0.3.0`.
- Update version-sensitive package/CLI tests.
- Update M6 durable release documentation.

Release boundary:

- This is still local-only release-candidate preparation.
- No public `v0.3.0` tag, push, package publication, or public release is
  authorized before the final human release decision.

Post-version-bump release checks:

- `pytest -q`: PASS, 393 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS, 100 source files checked.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Wheel build: PASS, generated `research_digest-0.3.0-py3-none-any.whl`.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --version`: PASS, reported
  `research-digest 0.3.0`.
- Installed CLI `status --json`: PASS with isolated data/config, initialized
  SQLite schema `16` and JSON config `5`; Windows scheduler status was
  unavailable in the Linux/WSL sandbox with a sanitized WSL socket message.
- Streamlit AppTest smoke: PASS, 17 passed.

## Final Integrated Audit Repair

Final Auditor:

- Scope: complete delta from `m6f-qualified` to the current M6/v0.3 candidate.
- Result: one IMPORTANT finding, no BLOCKER findings.
- Finding: Settings -> Automation -> Run now used the configured analyzer but
  did not pass `use_configured_preselector=True`, so that UI path could bypass
  configured model-based Stage-1 preselection and persist fail-open
  preselection evidence.

Repair:

- Settings Run now now invokes the shared automatic digest service with
  `use_configured_preselector=True`.
- Added deterministic regression coverage for the Settings Run-now Stage-1
  preselector boundary.
- Injected-analyzer test seams remain unchanged for deterministic tests.
- CLI/headless scheduled paths remain configured-preselector paths.

Closure Auditor:

- PASS, no BLOCKER or IMPORTANT findings.

Final post-repair qualification:

- `pytest -q`: PASS, 394 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS, 100 source files checked.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Wheel build: PASS, generated `research_digest-0.3.0-py3-none-any.whl`.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --version`: PASS, reported
  `research-digest 0.3.0`.
- Installed CLI `status --json`: PASS with isolated data/config, initialized
  SQLite schema `16` and JSON config `5`; Windows scheduler status was
  unavailable in the Linux/WSL sandbox with a sanitized WSL socket message.
- Installed CLI `backup --json`: PASS with isolated data/config, schema `16`.
- Streamlit AppTest smoke: PASS, 17 passed.

Release boundary:

- Package/runtime version is already `0.3.0`.
- No separate version-only commit is required after this final integrated
  repair because the authoritative version declarations are already `0.3.0`.
- No public `v0.3.0` tag, push, package publication, or public release is
  authorized before final human release authority.
