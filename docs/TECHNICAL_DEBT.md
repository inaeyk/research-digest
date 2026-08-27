# Technical Debt and Regression Backlog

## Import-order-sensitive preselection/analysis cycle

- Status: deferred; pre-existing and outside the integrated coverage,
  cancellation, cancellation-UI, and author-metadata freeze.
- Reproduction from the repository root:

  ```bash
  .venv/bin/pytest -q tests/test_db.py
  ```

- Current result: test collection imports `research_digest.preselection`, which
  imports `research_digest.analysis.base`; importing that submodule executes
  `research_digest.analysis.__init__`, which imports `codex_cli`; `codex_cli`
  then imports `AbstractPreselectionDecision` from the still-partially initialized
  `research_digest.preselection` module.
- Symptom: `ImportError: cannot import name 'AbstractPreselectionDecision' from
  partially initialized module 'research_digest.preselection'`.
- The normal complete `pytest -q` order initializes the modules differently and
  passes, so this remains a collection-order regression risk rather than a
  failure of the qualified integrated behavior.
- Future repair should remove the package-initializer dependency cycle without
  changing Stage-1 semantics, provider selection, or public imports, and should
  add an isolated-process regression test for the reproduction above.
