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
