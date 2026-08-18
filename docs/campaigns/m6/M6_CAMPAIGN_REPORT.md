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

Freeze state:

- Qualified local commit:
  `7208191b3aa66c21863ec63d21e7d1f60ebe82b0`.
- Qualified local annotated tag: `m6c-qualified`.
- Tag object: `bef7ae04a957e539c5a977fc569621eee8d38311`.
- Tag target: `7208191b3aa66c21863ec63d21e7d1f60ebe82b0`.

## M6-D Plan Freeze

The detailed M6-D plan is recorded in `CAMPAIGN_STATE.md`.

Key frozen decisions:

- M6-D search remains local-first and SQLite-backed; no embeddings, vector DB,
  or external search service.
- Search documents are derived/rebuildable from articles, tags, collections,
  notes, abstracts, and relevance context.
- Scientific connections are persisted suggestions with provenance, not facts.
- Relationship pairs are canonical unordered pairs for M6-D, with bounded
  deterministic local candidate selection before Codex reasoning.
- Viewing/searching existing Library data must not call Codex.
- Explicit per-article generation may call Codex through a focused provider
  boundary with prompt version `library_connections_v1`.
- User dismissal must durably hide a suggestion and prevent routine
  regeneration.
- M6-D is expected to use additive SQLite schema version `12`; JSON config is
  unchanged.

## M6-D Candidate

Implemented:

- Additive SQLite schema version `12` with rebuildable
  `library_search_documents` and durable `library_article_connections`.
- Derived local Library search documents built from saved article metadata,
  tags, collections, abstracts, notes, and latest relevance context.
- Library search backed by the derived SQLite-local search service while
  preserving tag and collection filters.
- Deterministic bounded candidate selection for saved-paper relationships using
  shared tags, categories, collections, and title/abstract token overlap.
- Canonical unordered connection pairs with provenance, optional confidence,
  generated timestamp, and soft dismissal.
- Explicit Codex connection provider boundary with prompt version
  `library_connections_v1`, bounded JSON schema, untrusted-source-text rules,
  and child-environment API-key redaction.
- Library UI section for related saved-paper suggestions, dismissal, and
  explicit per-article connection generation.
- JSON backup export of durable relationship suggestions.

Preserved:

- Search documents are derived/rebuildable, not authoritative user state.
- Viewing/searching Library data and existing connections does not call Codex.
- Connection generation is explicit and bounded to selected candidates.
- Connection suggestions do not mutate relevance analysis, feedback, history,
  tags, notes, collections, or article identity.
- Dismissed suggestions remain durable and hidden from routine display.

Deterministic candidate checks:

- `pytest`: PASS, 300 passed.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Live smoke:

- Synthetic live Codex connection smoke reached the Codex CLI but failed before
  model work because the CLI could not initialize in the read-only runtime.
  This is recorded as an environment/provider limitation for later human live
  smoke, not as a deterministic code failure.

Audit state:

- First fresh read-only M6-D Auditor found one IMPORTANT issue: unsaved related
  articles could still appear in the UI as related saved papers.
- Repair round 1 filters related-connection display to currently saved target
  and related endpoints while preserving the durable connection row for a
  future re-save.
- Repair round 1 also resolved the Auditor's MINOR/OPTIONAL privacy concern by
  excluding personal note text from Codex-facing connection candidate evidence
  while retaining local note search.
- M6-D repair round 1 deterministic checks: `pytest` PASS, 302 passed;
  `ruff check src tests` PASS; `mypy --strict src tests` PASS;
  `python -m compileall src tests` PASS; `git diff --check` PASS.
- Fresh read-only M6-D repair Auditor PASS.
- BLOCKER/IMPORTANT findings: none remaining.
- Audit repair rounds used: 1.
- Deferred MINOR/OPTIONAL: none active after repair; personal note text remains
  searchable locally but is excluded from Codex-facing connection candidate
  evidence.

Freeze state:

- Qualified local commit:
  `82c323d56c9ed9fbbdb8c36f602d03bd9d3d34b0`.
- Qualified local annotated tag: `m6d-qualified`.
- Tag object: `400e031ee29bf48b807e909d28304ea345b06b72`.
- Tag target: `82c323d56c9ed9fbbdb8c36f602d03bd9d3d34b0`.

## M6-E Plan Freeze

The detailed M6-E plan is recorded in `CAMPAIGN_STATE.md`.

Key frozen decisions:

- Daily relevance and Library memory remain separate layers; M6-E does not
  change relevance scoring, preselection, feedback, or analysis cache identity.
- New-paper Library context is bounded by deterministic local candidate
  selection before any Codex reasoning.
- Personal note text remains local/private by default and is excluded from
  Codex context prompts.
- Context suggestions and collection intelligence are persisted as additive
  provenance-bearing records, not as mutations of historical run snapshots or
  relevance analyses.
- UI wording must distinguish stored evidence from model-inferred suggested
  relationships.
- M6-E is expected to use additive SQLite schema version `13`; JSON config is
  unchanged.

## M6-E Candidate

Implemented:

- Additive SQLite schema version `13` with `library_context_suggestions` and
  `collection_intelligence_snapshots`.
- Bounded deterministic Library-context candidate selection for newly analyzed
  papers using shared tags/topics, categories, collections, and title/abstract
  token overlap.
- Explicit Codex context provider boundary with prompt version
  `library_context_v1`, bounded schema, untrusted-source-text rules, and no
  personal-note text in prompt input.
- Today page `Connections to your Library` display, dismiss controls, and
  explicit `Find Library context` generation action.
- Deterministic collection intelligence snapshots in the Library collection
  section, with stored evidence and dismiss/update controls.
- JSON backup export for context suggestions and collection intelligence
  snapshots.

Preserved:

- Daily relevance scoring, preselection, feedback, and analysis cache identity
  are unchanged.
- Viewing Today/Library/context does not call Codex.
- Historical run snapshots remain immutable.
- Personal notes remain searchable locally but are excluded from Codex context
  prompts and context candidate evidence.
- Collection intelligence and Library context use active saved-Library state
  rather than treating unsaved papers as active evidence.

Deterministic candidate checks:

- `pytest`: PASS, 310 passed after a test repair for button-label-based
  abstract UI smoke.
- `ruff check src tests`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.

Live smoke:

- Synthetic live Codex context smoke reached the Codex CLI but failed before
  model work because the CLI could not initialize in the read-only runtime.
  This is recorded as an environment/provider limitation for later human live
  smoke, not as a deterministic code failure.

Audit state:

- First fresh read-only M6-E Auditor found two IMPORTANT issues:
  collection-intelligence snapshots counted unsaved collection members as
  active evidence, and invalid provider output could partially persist an
  earlier valid context suggestion before raising on a later invalid item.
- Repair round 1 filters collection-intelligence evidence to currently saved
  Library entries.
- Repair round 1 validates the full provider-output batch before any context
  suggestion persistence.
- Added regressions for unsaved collection members and no partial persistence
  on invalid provider output.
- M6-E repair round 1 deterministic checks: `pytest` PASS, 312 passed;
  `ruff check src tests` PASS; `mypy --strict src tests` PASS;
  `python -m compileall src tests` PASS; `git diff --check` PASS.
- Fresh read-only M6-E repair Auditor PASS.
- BLOCKER/IMPORTANT findings: none remaining.
- Audit repair rounds used: 1.
- Deferred MINOR/OPTIONAL: context candidate eligibility can still spend prompt
  budget on a candidate whose only existing suggestion is collection-scoped and
  will later be skipped during assignment; no incorrect mutation occurs.

Freeze state:

- Qualified local commit:
  `fad6b8425bc14a956fb22f26f68cc485e46f71b9`.
- Qualified local annotated tag: `m6e-qualified`.
- Tag object: `2d09e095434b6d7a258b65a47d892e0b339e2b50`.
- Tag target: `fad6b8425bc14a956fb22f26f68cc485e46f71b9`.

## M6-F Final Release-Candidate Qualification

Implemented during the final gate:

- Added a deterministic Streamlit Library page smoke test using
  `streamlit.testing.v1.AppTest`.
- Repaired Library connection assignment so invalid provider batches cannot
  partially persist relationships before raising.
- Added regressions proving valid-then-duplicate and valid-then-unknown
  connection batches leave no persisted connection rows.

Final deterministic checks:

- `pytest`: PASS, 315 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `python -m pip wheel . --no-deps`.
- Isolated wheel install: PASS.
- Installed CLI smoke: PASS for `research-digest --version`.
- Installed CLI fresh status smoke: PASS; schema `13`, config `3`, no last run
  in an isolated `/tmp` working directory.
- Installed backup smoke: PASS.
- Streamlit Library smoke: PASS through AppTest.

Final audit:

- Fresh read-only final M6 Auditor reviewed the complete M6 delta from
  `v0.2.0`.
- Initial result: FAIL with one IMPORTANT finding. `assign_connection_suggestions`
  interleaved validation and writes, so a later invalid provider suggestion
  could leave an earlier connection persisted while the UI reported generation
  failure.
- Repair round 1 validates the entire provider batch before any connection
  writes.
- Focused repair Auditor result: PASS. No BLOCKER/IMPORTANT findings remain.

Upgrade/migration evidence:

- Additive migrations advance SQLite schema from v0.2 schema `8` to M6 schema
  `13`.
- JSON config remains version `3`.
- Deterministic tests cover fresh install, repeated migration/startup,
  v0.1.0/M2-style upgrade, backup/export, Codex unavailable, network
  unavailable/sanitized failures, packaging, installed CLI entry points, and
  Streamlit Library rendering.
- Existing profiles, articles, relevance analyses, feedback, synthesis/run
  history, source-date coverage, scheduler config, and History semantics remain
  preserved by the release matrix and substage tests.
- M6 data covered by deterministic tests includes saved articles, AI/user tags,
  tag suppressions, notes, collections, memberships, search documents,
  connections, Library context suggestions, and collection intelligence
  snapshots.

Privacy and safety evidence:

- No new secret-bearing configuration keys were added.
- Viewing Library, abstracts, tags, notes, connections, and context does not
  call Codex.
- Personal notes are excluded from Codex-facing connection/context prompts.
- Article metadata and abstracts are treated as untrusted text in prompt
  boundaries.
- Secret-pattern scan found only fake redaction-test strings and existing
  documentation examples; ignored local `.env`, SQLite, cache, and virtualenv
  files are not tracked.

Live/smoke limitations:

- M6-B/M6-D/M6-E synthetic Codex smokes reached the Codex CLI but could not
  complete model work in this sandbox because of provider/auth/runtime
  limitations. This is recorded as an environment limitation, not a deterministic
  code failure.
- Installed scheduler status smoke reports unsupported Windows Task Scheduler
  socket behavior in this environment; deterministic scheduler tests remain
  passing. First-class WSL2/Windows scheduler live validation remains a human
  environment smoke when release authority is granted.

Known limitations:

- arXiv-only source family.
- Abstract-level analysis only; no PDF/full-paper reading.
- No M3 RSS/journal/API/general-web sources.
- No vector database, embedding service, Redis, Celery, distributed runtime,
  multi-user authentication, or cloud requirement.
- AI tags, connections, and Library context require an available Codex runtime.
- AI-generated connections/context are provenance-bearing suggestions, not
  scientific facts.

Release notes draft:

- Saved Article Library with explicit save/remove from Today and History.
- Library page with sorting/filtering, relevance context, arXiv/PDF links, and
  original source abstract display.
- User tags, AI tags, AI provenance, and durable AI tag suppressions.
- Personal notes and collections/projects for saved papers.
- Local Library search over title, authors, tags, collections, abstracts, and
  notes where appropriate.
- AI-suggested relationships among saved papers with dismissal.
- Bounded Library context suggestions for newly analyzed papers.
- Lightweight collection intelligence snapshots.

User guide draft:

- Save papers deliberately with `Save to Library`; relevant papers are not
  saved automatically.
- Use the `Library` page to search, sort, inspect abstracts, add tags, edit
  notes, and manage collections.
- Use explicit AI actions to generate tags, saved-paper connections, or Library
  context when Codex is available.
- Remove AI suggestions to hide them durably; user tags and notes remain
  authoritative.
- Collections group papers without deleting papers when a collection is
  removed.
- Treat generated connections/context as suggested relationships grounded in
  stored evidence.

Suggested release commands after human approval:

```bash
git status --short --branch
pytest
ruff check .
mypy --strict src tests
python -m compileall src tests
git diff --check
git tag -a v0.3.0 -m "Research Digest v0.3.0" HEAD
git push origin feature/m6-scientific-library-memory
git push origin v0.3.0
python -m pip wheel . --no-deps --wheel-dir dist
```

Do not run these commands until the human release decision is made. The local
M6 feature qualification tag remains `m6-v0.3-qualified`; the public
`v0.3.0` tag should target the separate release-version commit that reports
package/runtime version `0.3.0`.

Final state:

- Campaign state is
  `M6_RELEASE_CANDIDATE_COMPLETE_AWAITING_HUMAN`.
- Suggested local qualification tag: `m6-v0.3-qualified`.
- Suggested public release tag target, if approved later: the v0.3.0
  release-version commit derived from `m6-v0.3-qualified`.
- No push, package publication, public version tag creation, or public release
  has been performed by this campaign.

## Final RC Refinement - Feedback Semantics And Library-Context Cost Gate

After the original M6 RC qualification, human review approved one final
refinement before v0.3 release consideration.

Changed behavior:

- The paper-card feedback UI now asks two independent questions:
  whether the paper matches the selected Interest Profile, and whether the user
  is personally interested in the paper.
- The ordinary UI shows the actual profile name, uses `Yes`, `No`, and
  `Unanswered`, and does not default unanswered papers to `No`.
- Profile calibration now consumes only the profile-match dimension.
  Personal-interest answers are stored for discovery/organization and do not
  redefine the current Interest Profile.
- The combination `profile_match=NO` and `personal_interest=YES` is stored as
  new-interest evidence, without automatically expanding or rewriting the
  current profile.
- Suggested Interests are generated conservatively from bounded local evidence,
  require explicit user approval to create a normal Interest Profile, support
  user edits before creation, and can be dismissed durably.
- Automatic Library-context reasoning now has a default threshold
  `automatic_library_context_threshold = 0.90`; below-threshold papers do not
  automatically invoke expensive Codex Library-context reasoning.
- Manual `Find Library connections` remains available regardless of relevance
  score.

Durable data changes:

- SQLite schema advances to `14`.
- JSON config advances to `4`.
- `article_feedback` now has nullable `profile_match` and
  `personal_interest` fields. Legacy `feedback_label` remains for compatibility.
- Legacy binary feedback migrates as:
  `RELEVANT -> profile_match YES, personal_interest NULL` and
  `NOT_RELEVANT -> profile_match NO, personal_interest NULL`.
- New durable suggested-interest records store profile scope, evidence article
  IDs, suggested name/description, explanation, provenance, dismissal state, and
  accepted profile linkage.
- Backup/export includes suggested-interest records and the new feedback fields.

Performance/call-count evidence:

- Deterministic tests verify relevance score `0.89` produces zero automatic
  Library-context generator calls at the default `0.90` threshold.
- Deterministic tests verify relevance score `0.90` is eligible and invokes the
  supplied generator when bounded Library candidates exist.
- Deterministic tests verify reused/cached analyses are skipped by automatic
  Library-context generation.
- Deterministic tests verify no saved Library means no unnecessary generator
  call, while manual context lookup below threshold still works.

Qualification evidence:

- `pytest`: PASS, 334 passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `python -m pip wheel . --no-deps`.
- Isolated wheel install: PASS.
- Installed CLI `--version`: PASS.
- Installed CLI `status --json`: PASS, schema `14`, config `4`.
- Installed CLI backup/export smoke: PASS.
- Streamlit AppTest smoke: PASS for two-question feedback controls,
  explicit `Unanswered`, persistence through rerun, manual connection action,
  abstract toggles, and Settings threshold display.

Audit evidence:

- Initial fresh read-only refinement Auditor: FAIL with one BLOCKER and three
  IMPORTANT findings.
- Repair round 1:
  explicit feedback clearing, theme-keyed suggestion dismissal, bounded
  evidence reads, and service/automation/UI threshold wiring.
- Fresh read-only repair Auditor: PASS with no BLOCKER, IMPORTANT, or MINOR
  findings.

Live smoke status:

- Real browser/served UI smoke for this final refinement remains pending human
  execution in the user environment.
- Network/Codex timing remains unsuitable for deterministic pass/fail in this
  sandbox; deterministic call-count tests cover the performance gate.

Current stop:

- Return for human live smoke and review.
- Do not commit, tag, push, publish a package, or create a public release until
  the human explicitly authorizes the next step.

## Final RC Refinement - Cost, Calibration, Scoring, And Progress

After the already-qualified M6/v0.3 RC refinement, human review requested one
additional refinement before live smoke and release consideration.

Changed behavior:

- Preselected-out cache-miss papers remain cheap: they are not sent to full
  relevance analysis for that run and do not receive generated summaries,
  why-it-matters text, reading priority, or automatic Library-context reasoning.
- Preselected-out cards keep source metadata, arXiv/PDF links where available,
  original source abstract display, and Save to Library.
- Saving a paper to Library records `personal_interest=YES` when the current
  profile context is known. It does not alter `profile_match`; unsaving does not
  set `personal_interest=NO`.
- Settings -> Analysis now exposes an intuitive Model effort slider. The stored
  internal value remains `preselection_fraction`, with
  `model_effort = 1 - preselection_fraction`.
- Settings -> Analysis / Library Intelligence now has a master
  `automatic_library_connections_enabled` toggle. Turning it off disables
  automatic digest-time Library-context model calls while preserving Library,
  tags, notes, collections, search, stored connections, and manual
  `Find Library connections`.
- The automatic Library context threshold remains default `0.90` and now clearly
  explains that it applies to a new paper's final profile relevance score and
  gates extra model work, not connection confidence.
- Research Digest now occasionally persists one quantitative human relevance
  calibration prompt per completed digest run. The default sampling probability
  is `0.20`; false sampling decisions are persisted as `SKIPPED` so reruns do
  not reroll the decision.
- Calibration prompts choose only below-threshold papers that passed
  preselection and received valid full analysis; preselected-out papers and
  unresolved papers are ineligible. Newly analyzed papers are preferred over
  reused analyses when both are eligible.
- The model relevance score is hidden until after the user submits a human
  0..1 score. Human and model scores are stored separately and no automatic
  score correction is applied in this refinement.
- Settings now includes a Scoring Guide explaining relevance score, profile
  threshold, preselection score/threshold, Model effort mapping, automatic
  Library threshold, Library connection confidence, and human calibration score.
- Digest runs now write low-frequency progress state to `app_runs`, including
  progress stage/message and intermediate counts after retrieval, preselection,
  analysis chunks, and terminal completion/failure.

Durable data changes:

- SQLite schema advances to `15`.
- JSON config advances to `5`.
- New table: `quantitative_relevance_calibrations`.
- New app-run fields: `progress_stage`, `progress_message`.
- New config fields:
  `automatic_library_connections_enabled`,
  `preselection_fraction`,
  `relevance_calibration_prompt_probability`.
- Backup/export includes quantitative relevance calibration records.

Quantitative score/threshold inventory:

- `relevance_score`: 0..1 LLM ordinal judgment of how strongly the paper
  matches the selected Interest Profile; relevant iff score is at least the
  profile's `relevance_threshold`. It is not a calibrated probability.
- `InterestProfile.relevance_threshold`: user/profile threshold in 0..1 used
  to classify analyzed papers as relevant.
- `preselection_score`: deterministic abstract/metadata plausibility score for
  cache-miss papers; it asks whether deeper analysis could plausibly find the
  paper relevant.
- `preselection_fraction`: internal 0..1 setting where `0` means no
  preselection filtering and maximum downstream model effort, while `1` means
  most aggressive filtering.
- `Model effort`: user-facing setting in 0..100%, mapped by
  `model_effort = 1 - preselection_fraction`.
- `preselection_threshold`: deterministic formula
  `preselection_fraction * relevance_threshold`.
- `automatic_library_context_threshold`: default `0.90`; gates extra automatic
  Library-context model work for newly analyzed digest papers.
- `Library connection confidence`: 0..1 or null. It is confidence that the
  specific stated scientific relationship between two papers is supported by
  the bounded supplied evidence. It is not profile relevance, a statistical
  interval, or a calibrated probability. The Codex connection/context prompts
  require confidence in their structured outputs and validation accepts 0..1 or
  null; validated non-dismissed suggestions are shown.
- `relevance_calibration_prompt_probability`: default `0.20`; Bernoulli
  probability for creating at most one quantitative human prompt per completed
  digest run.
- `human relevance calibration score`: user-provided 0..1 profile-relevance
  judgment, stored separately from personal interest and model relevance score.

Performance/call-count evidence:

- Deterministic tests verify preselected-out cache misses do not call the full
  analyzer.
- Deterministic tests verify all-preselected-out runs render as usable runs with
  original abstracts and no generated summaries.
- Deterministic tests verify automatic Library connections OFF produces zero
  automatic Library-context generator calls, even when a test generator is
  supplied and the analyzed paper score is high.
- Deterministic tests preserve the previous threshold behavior:
  score `0.89` produces zero automatic Library-context generator calls at the
  default `0.90`, while score `0.90` is eligible.
- Manual Library connection generation remains available below threshold.

Qualification evidence so far:

- `pytest`: PASS, 346 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `python -m pip wheel . --no-deps`.
- Dependency-resolving isolated wheel install: BLOCKED by environment DNS/PyPI
  access for declared dependencies, including `openai>=1.99.0`, even after the
  required network escalation retry.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`: PASS.
- Installed CLI `status --json`: PASS, schema `15`, config `5`.
- Installed CLI backup/export smoke: PASS.

Pending before human smoke:

- Fresh independent closure Auditor.

Current stop:

- Continue to package/install qualification and fresh Auditor.
- Do not commit, tag, push, publish a package, or create a public release before
  integrated qualification and human smoke.

### Repair Round 1

Fresh closure Auditor found no BLOCKER issues and two IMPORTANT issues:

- stale/crashed run recovery could leave progress fields in a nonterminal stage;
- JSON backup/export omitted the new app-run progress fields.

Repair outcome:

- Stale run recovery now sets terminal failed `progress_stage` and
  `progress_message` while marking unfinished runs failed.
- Backup/export now includes `progress_stage` and `progress_message` in run
  export records.
- The top-level campaign-state header now reflects schema `15`, config `5`, and
  the current repair-round qualification state.

Repair qualification:

- Focused regression tests: PASS, 18 passed.
- Full `pytest`: PASS, 346 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Repaired package build: PASS.
- Repaired no-deps isolated wheel install: PASS.
- Repaired installed CLI `--version`: PASS.
- Repaired installed CLI `status --json`: PASS, schema `15`, config `5`.
- Repaired installed CLI backup/export smoke: PASS.
- Dependency-resolving isolated wheel install remains environment-blocked by
  DNS/PyPI access for declared dependencies.

Focused repair Auditor found no BLOCKER issues. It found one IMPORTANT
documentation drift in the top-level migration-state summary and one MINOR
test-strength gap for exported `progress_message`.

Second repair outcome:

- Top-level campaign migration-state summary now includes schema `14` / config
  `4` and schema `15` / config `5`.
- Backup export regression test now asserts exported `progress_message`.

Final qualification:

- Full `pytest`: PASS, 346 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Final package build: PASS.
- Final no-deps isolated wheel install: PASS.
- Final installed CLI `--version`: PASS.
- Final installed CLI `status --json`: PASS, schema `15`, config `5`.
- Final installed CLI backup/export smoke: PASS.

Final state:

- The integrated refinement is qualified for human live smoke.
- Do not commit, tag, push, publish a package, or create a public release before
  explicit human authority.

## Final RC Startup Side-Effect Repair

Human live smoke found that starting `research-digest serve` appeared to create
or resume a `Legacy digest`, after which an explicit Run Digest click reported
that another digest was ongoing.

Root-cause trace:

- `research-digest serve` itself only launches Streamlit.
- Streamlit default Today render had startup side effects:
  `today.render` -> `_render_date_selection_control` ->
  `resolve_latest_available_source_date` ->
  `ArxivSource.resolve_latest_available_date` -> arXiv API fetch.
- Settings/Automation render also had startup side effects:
  `_render_coverage_overview` -> `build_automatic_coverage_plan` ->
  `ArxivSource.resolve_latest_available_date` -> arXiv API fetch.
- Today render also constructed the analyzer and automatic Library-context
  generator before the user clicked Run Digest.
- Deterministic tracing did not find a supported startup path that intentionally
  calls `run_digest_for_profile`, `run_automatic_digest_now`, or acquires the
  digest run lock. The new regression tests now fail on startup-time source
  fetches, provider construction, run-service calls, or `app_runs` insertion,
  and verify the digest lock remains available after startup render.

Repair:

- Today/latest-available selection is now read-only at render time and passes
  `DateSelection.latest_available()` through to the explicit run service.
- Analyzer and automatic Library-context generator construction moved behind the
  explicit Run Digest button.
- Settings/Automation coverage overview is DB-only on render. Pending dates are
  resolved only when Run Now is explicitly clicked.
- Suggested Interests generation is explicit. Settings now lists stored
  suggestions read-only during render and calls `refresh_suggested_interests`
  only after `Refresh suggested interests`.
- Manual `Find Library connections` now defers Library-context generator
  construction until the explicit button click.
- Legacy-format history remains display-only and is not auto-executed.

Regression coverage:

- Added `tests/test_streamlit_startup_side_effects.py`.
- Covers Today initial render, refresh/rerun, Settings initial render,
  legacy-history presence, History rendering, run-lock freedom after startup,
  one-click Run Digest service invocation, and no duplicate invocation after the
  post-click rerun.
- Covers Settings render with qualifying new-interest evidence and verifies it
  does not refresh/create Suggested Interests without an explicit click.

Qualification:

- Focused startup tests: PASS, 6 passed.
- Affected regression set: PASS, 76 passed.
- Full `pytest`: PASS, 351 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`, `status --json`, and backup smoke: PASS.

Pending:

- Human live smoke with the explicit serve/status checklist.

Focused Auditor result:

- BLOCKER: none.
- IMPORTANT: Settings render could mutate Suggested Interests by calling
  `refresh_suggested_interests` during ordinary page load. Repaired by making
  generation an explicit refresh action.
- MINOR/OPTIONAL: manual Library-context generator was constructed before the
  button click on existing result cards. Repaired by moving construction behind
  the explicit `Find Library connections` click.
- MINOR/OPTIONAL: campaign docs overstated lock-acquisition sentinel coverage.
  Repaired wording to state exactly what the tests enforce.

Focused repair Auditor result:

- PASS.
- BLOCKER: none.
- IMPORTANT: none.
- MINOR/OPTIONAL: add an extra AppTest around existing result-card render to
  prove manual Library-context generator construction remains deferred until
  `Find Library connections`. Code inspection confirms that behavior; no release
  blocker remains.

## Final RC Scheduler State Repair

Human live smoke found that Windows Task Scheduler reported the Research Digest
task as installed and `Ready`, with next run visible, while Settings rendered
`Automatic daily digest = OFF`. The previous Windows task result was
`3221225786`.

Root cause:

- The Windows scheduler status PowerShell script cast
  `$info.LastTaskResult` to `[int]`, which can overflow on Windows result codes
  above `System.Int32.MaxValue`.
- Settings represented any scheduler inspection failure as
  `bool(status.schedule and status.schedule.installed)`, which displays as OFF
  when status is unavailable.

Repair:

- Scheduler status now casts `LastTaskResult` to `[int64]`.
- Settings distinguishes scheduler state:
  - enabled: task installed and state is not `Disabled`;
  - disabled: task missing or state is `Disabled`;
  - unknown: scheduler status unavailable or parsing failed.
- A nonzero `LastTaskResult` is a previous-run warning only and does not disable
  the schedule.
- Unknown status renders `Schedule state unavailable`, with cautious disabled
  schedule mutation controls, and does not render an OFF daily-digest toggle.
- CLI status preserves unknown scheduler state as `status_available=false` and
  `installed=null` in JSON, and human-readable status says `Schedule: status
  unavailable` instead of `installed=False`.

Regression coverage:

- `tests/test_scheduler.py` covers large task-result parsing and verifies the
  PowerShell script uses `[int64]`.
- `tests/test_settings_page.py` covers enabled/disabled/unknown state semantics.
- `tests/test_settings_ui_smoke.py` covers visible Settings behavior for Ready
  with result `0`, Ready with result `3221225786`, Disabled, and status parsing
  failure.
- `tests/test_cli.py` covers JSON and human-readable scheduler status when
  scheduler inspection fails, ensuring unknown state is never represented as
  false/off.

Qualification:

- Focused scheduler/CLI/settings tests: PASS, 42 passed and 6 subtests passed.
- Full `pytest`: PASS, 361 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`, `status --json`, and backup smoke: PASS. In this
  sandbox, `status --json` reports scheduler inspection as unavailable with
  `installed=null`, which is the intended cautious fallback.

Pending:

- Human live smoke with Windows Task Scheduler enabled/disabled/status checks.

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

Human live evidence showed scheduled run `#43` remained `RUNNING` after the
Windows scheduled process ended:

- retrieved `198`;
- stored `58`;
- preselected `177`;
- skipped `21`;
- analyzed `70`;
- completed_at `null`;
- progress `Full analysis 70 / 177; Codex batch 15 / 36 (size 5).`

Root cause:

- Existing lock recovery was age-based only, with a six-hour default stale
  threshold.
- The old lock owner value stored only `pid:<uuid>`, not an inspectable PID,
  host, or process start identity, so the app could not prove the scheduled
  owner process was dead before the age threshold.
- Catchable interruption paths could bypass run finalization because the
  pipeline finalized only ordinary `Exception` failures.

Repair:

- New run-lock owners now include process PID, host, Linux process start ticks,
  and a nonce.
- Lock acquisition now:
  - blocks if the recorded owner is inspectably alive;
  - immediately recovers inspectably dead owners;
  - treats PID reuse as dead when start ticks differ;
  - keeps age-based fallback for unknown/uninspectable owners.
- Recovery marks abandoned unfinished runs terminal `FAILED`, preserves existing
  retrieved/preselected/analyzed counts and progress information, stores a
  sanitized explanation, releases stale ownership, and permits a new run.
- Added `research-digest recover-abandoned-run --run-id <ID>` as an explicit
  application-level recovery path. Legacy/uninspectable owners require
  `--force-uninspectable-owner` after the human verifies no owner process is
  alive.
- `research-digest status --json` now reports `run_lock` owner state. For the
  live legacy lock it reports `owner_state = "unknown"` instead of implying the
  owner is active.
- Catchable `KeyboardInterrupt`/`SystemExit` now finalizes the current run as
  `FAILED` with a sanitized interruption message before re-raising.

Regression coverage:

- `tests/test_run_locks.py` covers process-owner liveness, missing process, PID
  reuse, legacy unknown owners, and cross-host unknown owners.
- `tests/test_run_lifecycle.py` covers active-owner blocking, dead-owner
  recovery before the age threshold, forced recovery for legacy owners,
  interrupted scheduled-run recovery, progress/count preservation, retry after
  recovery, cache reuse of already-valid analyses, History preservation,
  catchable interruption cleanup, and interruption after a successful analysis
  chunk preserving the durable analyzed count.
- `tests/test_cli.py` covers lock-state status output and the explicit recovery
  command with and without legacy-owner force.
- Prior scheduler-state parsing/UI tests remain passing.

Qualification:

- Focused stale-run/scheduler/CLI tests after repair round 1: PASS, 61 passed
  and 6 subtests passed.
- Full `pytest`: PASS, 376 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS.
- No-deps isolated wheel install: PASS.
- Installed CLI `--version`, `status --json`, and backup smoke: PASS.

Pending:

- Human live recovery smoke for run `#43`; do not re-enable automatic scheduling
  until that passes.

Audit repair round 1:

- Initial stale-run recovery Auditor found one IMPORTANT issue: catchable
  interruption during analysis batching could overwrite already persisted
  partial analysis progress with stale in-memory counters.
- Repair reads the latest durable run counters during exception finalization
  and preserves the maximum count values when marking the run terminal.
- Added a deterministic regression interrupting after one successful analysis
  chunk and verifying the failed terminal run keeps the analyzed count.
- Implemented the Auditor's optional boot-id strengthening for process-owner
  identity where Linux exposes `/proc/sys/kernel/random/boot_id`.

Focused closure Auditor:

- PASS.
- BLOCKER: none.
- IMPORTANT: none.
- MINOR/OPTIONAL: add a direct boot-ID mismatch test for the optional hardening
  branch. No release-blocking issue remains.

## v0.3 RC Preselection Calibration Repair

Human live diagnostics for run `#46` showed that the preselection threshold was
being enforced correctly, but the production `TermOverlapPreselector` was
scientifically over-permissive:

- expected cutoff: `0.70 * 0.70 = 0.49`;
- screened pass rate: `21 / 26 = 80.8%`;
- median reconstructed lexical preselection score: `0.70`;
- median final relevance among new analyses: `0.22`;
- 20 of 21 newly analyzed papers ultimately fell below the profile relevance
  threshold.

Repair implemented:

- Added `CodexAbstractPreselector` as the production Codex Stage-1 preselector.
- Added `OpenAIAbstractPreselector` for OpenAI provider parity.
- Added `build_configured_preselector` and `PreselectorRegistry` so Today,
  Automation Run Now, scheduled/headless catch-up, and CLI-shared automation use
  the same provider-backed Stage-1 boundary.
- Retained `TermOverlapPreselector` for deterministic testing/offline fallback
  only; it is no longer explicitly constructed by normal production UI or
  automation paths.
- Stage-1 output is intentionally minimal: `article_id` and
  `preselection_score`.
- Rejected papers remain abstract-only in ordinary presentation and do not get
  full relevance analysis or generated prose.
- Model preselection is bounded and retrying:
  - default chunk size `20`;
  - retry chunk sizes `20`, `10`, `1`;
  - duplicate/unknown/missing/malformed IDs are rejected;
  - only unresolved IDs are retried;
  - provider failure fails open to full analysis with explicit
    `UNAVAILABLE_FAIL_OPEN` evidence.
- Cached valid full analyses bypass Stage 1 and are recorded as
  `REUSED_ANALYSIS_BYPASS`.

Frozen Stage-1 rubric:

- Question: "From the title and abstract alone, how plausible is it that a
  deeper relevance analysis would find this paper meaningfully relevant to the
  selected Interest Profile?"
- `preselection_score` remains an ordinal `0..1` judgment, not a calibrated
  probability.
- Bands:
  - `0.00-0.19`: no substantive plausible connection;
  - `0.20-0.39`: weak/general adjacency;
  - `0.40-0.59`: plausible but indirect connection;
  - `0.60-0.79`: strong plausible relevance from the abstract;
  - `0.80-1.00`: direct/core apparent match.
- The prompt explicitly rejects keyword-only scoring and broad shared
  vocabulary as sufficient grounds for high scores.

Persistence and migration:

- Schema version: `15 -> 16`.
- Added table `preselection_decisions`.
- Persisted fields include run id, article id, profile/source semantic
  fingerprints, preselection score, threshold used, pass/reject, decision
  origin, stage, preselector version, optional reason, and creation time.
- Run snapshots now include `preselection_decisions` for immutable historical
  interpretability.
- JSON export now includes `preselection_decisions`.
- Config version unchanged.

UI/reporting:

- Settings Scoring Guide now describes preselection as model-generated
  abstract-level first-impression relevance/plausibility, not deterministic
  lexical overlap.
- Today preselected-out section now says papers were skipped by Stage-1
  abstract preselection before full analysis.
- Existing clearer run accounting terminology remains preserved:
  Retrieved, Already analyzed / reused, Screened this run, Passed preselection,
  Preselected out, New full analyses, Reused full analyses, Total analyzed,
  Relevant.

Regression coverage added:

- model preselector valid batch;
- low score rejected;
- score exactly at threshold passes;
- high score passes;
- final short chunk;
- missing result retry without rescoring successful items;
- duplicate/unknown/malformed result retry;
- bounded retry exhaustion/fail-open;
- rejected paper invokes no full analyzer;
- survivor invokes full analyzer;
- cached full analysis bypass;
- old preselector-version decisions are not reused as a cache;
- persisted score/threshold/version/origin;
- schema migration/idempotency;
- backup/export inclusion;
- production provider factory no longer returns term overlap for Codex;
- Scoring Guide wording avoids obsolete deterministic preselection semantics.

Qualification:

- `pytest -q`: PASS, 389 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `pip wheel . --no-deps --wheel-dir
  /tmp/research-digest-wheel`.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --help`: PASS.

Run `#46` benchmark status:

- The live default DB was found read-only at
  `/home/inaeyk/.local/share/research-digest/research_digest.sqlite3`.
- Run `#46` exists at schema 15 and its 26 originally screened papers were
  reconstructed from snapshot plus article rows without modifying the DB.
- Sandboxed Codex execution failed before model execution with Codex app-server
  initialization blocked by read-only filesystem.
- An attempted outside-sandbox benchmark was rejected by approval policy because
  it would send private article abstracts from the local user DB to Codex/LLM
  without explicit human authorization.
- No benchmark scores were produced. This is a live-smoke authorization blocker,
  not a deterministic code failure.

Focused Auditor:

- In progress at the time of this report update.

Audit repair round 1:

- Initial focused Auditor result: BLOCKER.
- BLOCKER: deterministic CLI/Automation paths with injected `FakeAnalyzer`
  could still construct the real Codex Stage-1 preselector because
  `run_automatic_digest_now` had no preselector injection seam.
- Repair:
  - `run_automatic_digest_now` now accepts `preselector` for deterministic
    callers.
  - `run_cli` and `_run_digest_command` now accept the same test seam.
  - Tests using `FakeAnalyzer` inject `UnavailableFailOpenPreselector`, so they
    cannot call live Codex while still exercising downstream analysis behavior.
  - Production callers that omit the injection continue to use
    `build_configured_preselector`.
- IMPORTANT: scheduled tasks did not preserve `RESEARCH_DIGEST_CONFIG_DIR`,
  which could make scheduled/headless runs ignore UI-saved M6 analysis settings
  in custom config-dir deployments.
- Repair:
  - scheduled environment includes `RESEARCH_DIGEST_CONFIG_DIR`;
  - scheduler tests verify it appears in the Windows action environment;
  - existing no-secret assertions remain in force.

Post-repair qualification:

- Focused CLI/Automation/Scheduler/Provider tests: PASS, 36 passed and 6
  subtests passed.
- `pytest -q`: PASS, 389 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `pip wheel . --no-deps --wheel-dir
  /tmp/research-digest-wheel-2`.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --help`: PASS.

Focused closure Auditor:

- In progress.

Audit repair round 2:

- Closure Auditor result: IMPORTANT.
- Finding: direct headless Automation calls with injected fake analyzer but no
  preselector could still construct live Codex Stage-1 preselection.
- Repair:
  - `run_automatic_digest_now` now defaults injected-analyzer/no-preselector
    calls to `UnavailableFailOpenPreselector`;
  - production CLI passes `use_configured_preselector=True`, preserving the
    provider-backed production Stage-1 path;
  - direct regression test patches the configured preselector builder to raise
    and proves an injected `FakeAnalyzer` call does not construct it.

Final deterministic qualification:

- Focused Automation/CLI tests: PASS, 21 passed.
- `pytest -q`: PASS, 391 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Package build: PASS with `pip wheel . --no-deps --wheel-dir
  /tmp/research-digest-wheel-4`.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --help`: PASS.

Final state for human review:

- Deterministic repair is qualified.
- Audit repair budget for this repair is fully used: initial candidate plus two
  audit-driven repair rounds.
- Final focused closure Auditor: PASS, 38 focused tests passed.
- Live run `#46` benchmark remains pending explicit human authorization because
  it would send local article abstracts from the user DB to the model provider.

## Authorized Run #46 Live Benchmark Attempt

Human authorized a read-only live Codex benchmark of the 26 saved run `#46`
title/abstract records that originally required Stage-1 screening.

Benchmark setup:

- SQLite opened read-only.
- No run, article, analysis, feedback, coverage, or Library state was modified.
- `CodexAbstractPreselector` was used with profile threshold `0.70`,
  preselection fraction `0.70`, and cutoff `0.49`.
- Historical final relevance scores were compared only after Stage-1 returned.

Result:

- Codex did not execute the model prompt.
- The normal Research Digest Codex boundary
  `codex exec --ephemeral --sandbox read-only` failed while initializing the
  in-process app-server client with a read-only filesystem error.
- Every article received explicit `UNAVAILABLE_FAIL_OPEN` behavior.
- Because no `preselection_score` values were produced:
  - median new Stage-1 score is undefined;
  - Spearman correlation is undefined;
  - scientific calibration of the new rubric against run `#46` could not be
    evaluated locally.

Aggregate fail-open benchmark:

- total screened: 26.
- passing `>= 0.49`: 26 via fail-open.
- rejected `< 0.49`: 0.
- pass rate: 100% via fail-open.
- known historical final scores: 21.
- median historical final relevance among known scores: 0.22.
- known final `<= 0.20`: 10, all fail-open/pass.
- known final `>= 0.70`: 1, fail-open/pass.
- obviously low-final papers that would still receive full analysis: 10 among
  known low-final papers.
- genuinely relevant papers incorrectly rejected: 0.
- estimated full-analysis calls avoided versus old run `#46`: 0.

Live new-paper smoke:

- arXiv source-only smoke was attempted with no user DB writes.
- Sandbox attempt failed DNS resolution for arXiv.
- Outside-sandbox attempt also failed DNS resolution for arXiv.
- A real disposable live digest could not be completed in this environment.

Conclusion:

- Deterministic code qualification remains PASS.
- Local live benchmark is inconclusive and should not be treated as a
  human-live candidate PASS.
- Before v0.3 freeze, rerun benchmark/smoke in a live environment where Codex
  can initialize under the app's read-only Codex boundary and arXiv DNS/API
  access works.

## Human-Run Run #46 Benchmark Evidence

The human reran the read-only Stage-1 benchmark from an ordinary WSL shell.

Observed run `#46` comparison:

- old lexical Stage 1 passed `21 / 26 = 80.8%`.
- new model Stage 1 at 30% Model effort passed `3 / 26 = 11.5%`.
- Spearman Stage-1 vs final relevance was approximately `0.87`.
- All 10 papers with historical final relevance `<= 0.20` were rejected.
- One historically relevant paper was incorrectly rejected at 30% effort:
  Stage-1 score `0.46`, final relevance `0.74`.
- The false negative was fifth-highest by Stage-1 score and only `0.03` below
  the 30%-effort cutoff `0.49`.

Conclusion:

- The model-based Stage-1 ranking is strong.
- The remaining issue is the default effort/cutoff choice, not the prompt or
  rubric.
- Do not tune the prompt against run `#46`.

Product refinement:

- Default Model effort for new/default configuration changes to 40%.
- This maps to `preselection_fraction = 0.60`.
- At relevance threshold `0.70`, the derived Stage-1 cutoff is `0.42`.
- Projected run `#46` behavior at 40% effort:
  - `5 / 26` pass;
  - the known relevant paper is preserved;
  - all known final `<= 0.20` papers remain rejected;
  - 16 full analyses avoided versus old lexical Stage 1.
- Existing saved user settings are preserved.
- Future automatic effort recommendations remain deferred until enough human
  calibration evidence accumulates.

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

## Final Integrated M6/v0.3 Feature Freeze

The human final smoke accepted the complete integrated M6/v0.3 candidate.

Accepted live-smoke behaviors:

- Settings -> Model effort includes a clear first-user worked example.
- The example uses the current relevance threshold, Model effort, and derived
  Stage-1 cutoff, and explains the above/below-cutoff behavior plus the
  speed/cost versus false-negative tradeoff.
- Changing Model effort / relevance threshold updates the example correctly.
- Today and History preselected-out cards remain minimal and do not show
  generated summary, relevance reason, reading priority, or why-it-matters.
- Show abstract displays original source content without triggering analysis.
- Two-axis feedback, quantitative calibration, automatic Library
  toggle/threshold, Model effort control, Scoring Guide, Suggested Interests,
  Library/tags/notes/collections/connections, stale-run recovery, and scheduler
  repairs remain accepted.

Final feature-candidate deterministic/package gate:

- `pytest -q`: PASS, 393 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS, 100 source files checked.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Wheel build before version bump: PASS,
  `research_digest-0.2.0-py3-none-any.whl`.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --version`: PASS, reported
  `research-digest 0.2.0` before version bump.
- Installed CLI `status --json`: PASS with isolated data/config, schema `16`
  and config `5`.
- Streamlit AppTest smoke: PASS, 17 passed.

The feature freeze remains local only. No push, public `v0.3.0` tag, package
publication, or public release was created.

## v0.3.0 Release-Version Candidate

Local feature freeze:

- Qualified feature commit: `3383ab360d5af0fb17263204863e7bfd5f284ac1`.
- Local qualification tag: `m6-v0.3-qualified`.

Release-version commit scope:

- `pyproject.toml` package version: `0.3.0`.
- `research_digest.__version__`: `0.3.0`.
- Version-sensitive package/CLI tests updated to `0.3.0`.
- No schema or config migration change; SQLite schema remains `16`, JSON
  config remains `5`.

Post-version-bump release checks:

- `pytest -q`: PASS, 393 passed and 9 subtests passed.
- `ruff check .`: PASS.
- `mypy --strict src tests`: PASS, 100 source files checked.
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- Wheel build: PASS, `research_digest-0.3.0-py3-none-any.whl`.
- Isolated no-deps wheel install: PASS.
- Installed CLI `research-digest --version`: PASS, reported
  `research-digest 0.3.0`.
- Installed CLI `status --json`: PASS with isolated data/config, schema `16`
  and config `5`.
- Streamlit AppTest smoke: PASS, 17 passed.

Major v0.3.0 features:

- Scientific Library for explicit saved articles.
- User and AI tags with provenance and AI-tag suppression.
- Notes and collections/projects.
- Local Library search and persisted paper-connection suggestions.
- Longitudinal Library context for new digest papers.
- Two-axis feedback separating profile match from personal interest.
- Suggested Interests from coherent outside-profile-but-interesting evidence.
- Quantitative human relevance calibration prompts.
- Model-based Stage-1 preselection with durable per-run preselection evidence.
- Model effort control, automatic Library-connection toggle/threshold, Scoring
  Guide, and improved long-run progress reporting.
- Date-native v0.2 digest, scheduler/catch-up, coverage calendar, History, and
  abstract-toggle behavior are preserved.

Known limitations:

- arXiv-only source family.
- Abstract-level analysis only; no full-paper/PDF deep reading.
- No vector database or semantic embedding infrastructure.
- Library intelligence is local-first and bounded, but model-generated
  connections remain suggestions rather than scientific facts.
- Public release, package publication, and public `v0.3.0` tag remain blocked
  pending final human authority.
