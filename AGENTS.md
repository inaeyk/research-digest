# Research Digest

## Development rules

- This is a small personal research-information extractor.
- Keep the architecture simple and explicit.
- Prefer standard Python and small focused modules over frameworks.
- Do not introduce distributed systems, vector databases, queues, Docker,
  authentication, or other infrastructure unless explicitly requested.
- SQLite is the persistent store.
- Streamlit is the UI.
- All source-specific retrieval logic must live behind a source adapter interface.
- LLM access must live behind a provider interface so it can be mocked in tests.
- Never hard-code API keys.
- Never commit secrets or .env files.
- Network-dependent behavior must be separable from deterministic unit tests.
- Tests must not require live arXiv or OpenAI access.
- Use typed Python.
- Run ruff, mypy, and pytest when available.
- Do not commit or push unless explicitly instructed.
- Do not broaden the task beyond the current milestone.
