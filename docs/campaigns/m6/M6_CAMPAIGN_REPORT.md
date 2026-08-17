# M6 Campaign Report

## Baseline Recovery

- Repository root: `/home/inaeyk/researchrepo/research-digest`.
- CodeGraph: no `.codegraph/` directory exists at repository root.
- Starting branch before M6 branch creation: `master`.
- M6 branch created: `feature/m6-scientific-library-memory`.
- Latest qualified v0.2 code state:
  `fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b`.
- Local `v0.2-rc-qualified` annotated tag object:
  `0a5ec71c000998144561f18aeb154ad65973af7e`; target:
  `fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b`.
- Local `v0.2.0` annotated tag object:
  `209a7c2d47eb6a5af6c3613aef0137f0d3f9232f`; target:
  `fe92e77a3fce4037c0bf4ecbb0a7ce964763eb8b`.
- Local `origin/master` and local `origin/HEAD` resolve to the same v0.2
  commit.
- Online remote verification with `git ls-remote --heads --tags origin` failed
  with DNS resolution failure for `github.com` before and after network
  escalation.
- Worktree was clean before M6 branch creation.
- Package/runtime version: `0.2.0`.
- SQLite schema version: `8`.
- JSON config version: `3`.

Conclusion:

- No uncommitted qualified v0.2 RC repair remains.
- A durable clean v0.2 baseline commit exists.
- A local public-style `v0.2.0` tag exists and targets the same qualified v0.2
  commit.
- No human product decision is required to identify the M6 baseline.

## Architecture Recovery Notes

- SQLite persistence is centralized in `research_digest.db.Database`.
- Migrations are additive, ordered by `SchemaMigration`, and guarded by
  `CURRENT_SCHEMA_VERSION`.
- Existing schema-changing upgrades create a pre-migration SQLite backup for
  existing DBs.
- JSON config is versioned in `research_digest.config`, rejects secret keys,
  and stores no API keys.
- Article identity is stable through the `articles` table unique constraint on
  `(source, source_article_id)`.
- Current `Article` rows store title, authors, original normalized abstract,
  categories, publication/update timestamps, arXiv abstract URL, and optional
  PDF URL.
- Relevance analyses are keyed by `article_id`, profile id, and profile
  semantic fingerprint.
- Feedback is keyed by `article_id`, profile id, and profile semantic
  fingerprint.
- Historical run snapshots are immutable JSON records stored separately from
  normalized Articles and analyses.
- Streamlit navigation is centralized in `research_digest.ui.app._build_pages`.
- Today and History paper cards already use shared abstract display helpers
  keyed by stable source/article identity.

## M6-A Plan Freeze

The detailed M6-A plan is recorded in `CAMPAIGN_STATE.md`.

Implementation will begin only after this baseline/plan commit or staged state
is established on `feature/m6-scientific-library-memory`.

Key planned design choice:

- Library state is a new article-centric durable layer keyed by existing
  `articles.id`. It must not mutate historical snapshots, rerun analysis, or
  duplicate Articles.

Initial risks to watch:

- History snapshot cards may lack enough normalized Article linkage in very old
  records. M6-A should resolve by `source` and `source_article_id` when
  possible and degrade clearly when not possible.
- Current available relevance context is profile-semantic and may have multiple
  analyses per Article. M6-A should present it as best-effort context without
  changing relevance semantics.
- Library UI controls must use stable keys and avoid accidental analyzer calls
  or DB writes on mere rendering.

## M6-A Qualified Freeze

Implemented:

- Additive SQLite schema version `9` with article-centric
  `library_articles`.
- Idempotent save, remove, re-save, source-identity save/remove, and saved-state
  lookup through a focused Library service boundary.
- A new Library page in Streamlit navigation.
- Save/remove controls on Today analyzed, Today preselected-out, Today
  analysis-unavailable, and History article cards where a durable source
  identity is available.
- Library listing with title, authors, source/publication date, saved date,
  arXiv/PDF links, original abstract display, basic sorting/filtering, and
  best-effort current relevance context.
- JSON backup export of Library membership state.

Preserved:

- Historical run snapshots remain immutable.
- Articles, analyses, feedback, coverage, scheduler state, and run history are
  not deleted or rewritten by Library remove.
- Saving/removing does not invoke analyzer/Codex paths.
- Abstract display remains sourced from the stored Article abstract.

Deterministic candidate checks:

- `pytest`: PASS, 268 passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Audit state:

- Fresh read-only M6-A Auditor PASS.
- BLOCKER/IMPORTANT findings: none.
- Audit repair rounds used: 0.
- Deferred MINOR/OPTIONAL: dedicated Streamlit click smoke for save/remove
  controls may be added later; current deterministic service/helper coverage
  passed.

Freeze state:

- Qualified local commit:
  `17e047c325bb61008cf39b9a135bea02bb63a968`.
- Qualified local annotated tag: `m6a-qualified`.
- Tag object: `ed9f887058f87135cfa7ff0e4f02fdb579b7398b`.
- Tag target: `17e047c325bb61008cf39b9a135bea02bb63a968`.

## M6-B Plan Freeze

The detailed M6-B plan is recorded in `CAMPAIGN_STATE.md`.

Key frozen decisions:

- Library tags are distinct from `matched_topics` and from relevance-analysis
  cache identity.
- M6-B uses additive SQLite schema version `10`.
- Tag identity is normalized centrally while preserving readable display text.
- USER and AI assignments have first-class provenance and can coexist for the
  same normalized tag.
- Removing an AI tag creates a durable suppression so routine generation does
  not simply re-add it.
- AI tag generation is explicit and only for saved Library articles. Viewing
  tags or opening the Library page must not call Codex or mutate data.
- AI tag generation uses a separate bounded Codex prompt, version
  `library_ai_tags_v1`, instead of forcing historical article reanalysis or
  changing `AnalysisResult`.

## M6-B Candidate

Implemented:

- Additive SQLite schema version `10` with `library_tags`,
  `library_tag_assignments`, and `library_ai_tag_suppressions`.
- Central tag normalization with case/whitespace equality and readable display
  labels.
- USER and AI tag assignment CRUD with provenance-specific identity.
- Durable AI suppression tombstones when a user removes an AI tag.
- Explicit saved-article AI tag generation service that respects suppressions
  by default and does not change relevance-analysis cache semantics.
- Codex CLI tag generator with prompt version `library_ai_tags_v1`, bounded
  JSON schema, untrusted-source-text rules, read-only ephemeral execution, and
  child-environment API-key redaction.
- Library UI sections for User tags and AI tags, user add/remove, AI
  remove/suppress, and explicit AI generate/regenerate actions.
- JSON backup export for tags, assignments, and suppressions.

Preserved:

- `matched_topics` remain relevance-analysis context, not Library tags.
- Viewing/listing tags does not call Codex and does not mutate the database.
- User tags survive AI regeneration.
- Removing AI tags does not remove same-name user tags.
- Ordinary digest reruns do not generate or re-add AI tags.

Deterministic candidate checks:

- `pytest`: PASS, 283 passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Live smoke:

- Synthetic live Codex tag smoke reached the Codex CLI but exited non-zero with
  the sanitized authentication/usage-limits message. This is recorded as an
  environment/provider limitation for later human live smoke, not as a
  deterministic code failure.

Audit state:

- First fresh read-only M6-B Auditor found one IMPORTANT issue: regeneration
  removed existing AI tags/suppressions before provider success.
- Repair round 1 moved provider generation before local replacement and added a
  failed-regeneration regression test.
- Fresh read-only M6-B repair Auditor PASS.
- BLOCKER/IMPORTANT findings: none remaining.
- Audit repair rounds used: 1.
- Deferred MINOR/OPTIONAL: future broader regeneration replacement flows would
  benefit from a single atomic DB helper; current supported paths are covered.

Freeze state:

- Qualified local commit:
  `104780a0ba9c98cd9663ef8d1088cb9472d53e09`.
- Qualified local annotated tag: `m6b-qualified`.
- Tag object: `6d4836113b38ed348a7a0d36527473f1321c0de9`.
- Tag target: `104780a0ba9c98cd9663ef8d1088cb9472d53e09`.

## M6-C Plan Freeze

The detailed M6-C plan is recorded in `CAMPAIGN_STATE.md`.

Key frozen decisions:

- Notes and collections attach to stable Article identity, not run snapshots.
- One user-authored note per Article in M6-C; empty/whitespace save clears the
  note.
- Notes are local/private and no Codex/analyzer call is made when viewing or
  editing them.
- Collections/projects are lightweight named groupings; deleting a collection
  deletes memberships only, not papers or other scientific state.
- Notes and memberships survive ordinary unsave/resave so user work is not
  lost.
- M6-C uses additive SQLite schema version `11`; JSON config is unchanged.

## M6-C Candidate

Implemented:

- Additive SQLite schema version `11` with `library_article_notes`,
  `library_collections`, and `library_collection_memberships`.
- Focused `research_digest.collections` service for note CRUD, collection CRUD,
  membership add/remove, collection/tag filters, and name normalization.
- Library page note editor with explicit save/clear semantics.
- Library page collection creation, rename, delete, article membership
  add/remove, and filters by collection and tag.
- JSON backup export for notes, collections, and memberships.

Preserved:

- Notes and collections attach to Article identity, not run snapshots.
- Empty/whitespace note save clears the note.
- Viewing/listing notes and collections does not call Codex/analyzers.
- Unsave/resave preserves notes and memberships.
- Deleting a collection deletes memberships only, not papers, notes, tags,
  analyses, feedback, history, or Library saved state.

Deterministic candidate checks:

- `pytest`: PASS, 290 passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Audit state:

- Fresh read-only M6-C Auditor PASS.
- BLOCKER/IMPORTANT findings: none.
- Audit repair rounds used: 0.
- Deferred MINOR/OPTIONAL: Library tag filter options may include tags retained
  only for AI suppression/tombstone history, which can yield no-result filter
  options.
