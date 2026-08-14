# Research Digest

A minimal personal research-information extractor. The MVP lets you define natural-language
interest profiles, configure an arXiv source, fetch recent papers, analyze title and abstract
relevance with an LLM provider, and review a ranked digest in Streamlit.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional:

```bash
export RESEARCH_DIGEST_ANALYZER=codex
export RESEARCH_DIGEST_CODEX_MODEL=...
```

The default analyzer provider is `codex`. This path requires the Codex CLI to
be installed and already signed in with ChatGPT. It uses the CLI's saved
ChatGPT-managed authentication, not `OPENAI_API_KEY`.

Use subscription-backed Codex analysis:

```bash
unset OPENAI_API_KEY
export RESEARCH_DIGEST_ANALYZER=codex
streamlit run src/research_digest/ui/app.py
```

Use OpenAI API analysis instead:

```bash
export RESEARCH_DIGEST_ANALYZER=openai
export OPENAI_API_KEY=...
export OPENAI_MODEL=...
```

`OPENAI_MODEL` defaults to `gpt-5-mini`. `RESEARCH_DIGEST_CODEX_MODEL` is
optional; when unset, the installed Codex CLI and ChatGPT account use their
normal configured/default model.

## Run

```bash
streamlit run src/research_digest/ui/app.py
```

After a digest completes, the Today page shows run-specific retrieval and
analysis counts. You can switch between relevant papers, all analyzed papers,
and below-threshold papers, and each paper indicates whether its analysis was
newly generated for the run or reused from SQLite.

## Tests

```bash
pytest
ruff check .
mypy src
```

## Architecture

The application uses a small `src` layout:

- `models.py` defines normalized domain objects independent of source-specific payloads.
- `db.py` persists profiles, arXiv configuration, articles, relevance analyses, and run
  history in SQLite using `sqlite3`.
- `sources/` contains the source adapter abstraction and the arXiv Atom API implementation.
- `analysis/` contains the LLM provider protocol, deterministic `FakeAnalyzer`,
  `CodexCLIAnalyzer`, and `OpenAIAnalyzer`.
- `pipeline.py` orchestrates fetch, store, analyze, filter, and rank.
- `ui/` contains the Streamlit multipage app.

Network access is isolated to source adapters and analyzer providers. Tests use saved fixtures,
mocked Codex subprocesses, and the fake analyzer, so they do not require live arXiv, Codex, or
OpenAI access.
