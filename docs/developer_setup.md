# Developer Setup

## Requirements

- Python 3.10+
- SQLite (bundled with standard Python builds)
- Optional: Ollama for local model-backed assistant behavior

## Environment setup

### Windows (Git Bash)

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

## Project structure

- `src/ben0/db/` — schema and sessions
- `src/ben0/ingest/` — ingest adapters and normalization
- `src/ben0/synthetic/` — demo dataset generation
- `src/ben0/validation/` — deterministic rules and engine
- `src/ben0/retrieval/` — chunking, indexing, search
- `src/ben0/tickets/` — review ticket helpers
- `src/ben0/reports/` — Markdown reporting
- `src/ben0/dashboard/` — metrics and UI
- `src/ben0/assistant/` — persona, prompts, tools, orchestration, adapters
- `tests/` — end-to-end smoke tests and focused module tests

## Running tests

```bash
pytest -v
```

## Adding a validation rule

1. Implement a function in `src/ben0/validation/rules.py`
2. Return one or more `ValidationFinding` objects
3. Add the function to `VALIDATION_RULES`
4. Add a focused test in `tests/test_validation.py`

## Adding an ingest adapter

1. Create a loader in `src/ben0/ingest/`
2. Reuse normalization helpers from `normalize.py`
3. Follow the `get_session` / commit / rollback pattern used by existing ingest modules
4. Return a `dict[str, int]` summary of inserted records
5. Add CLI wiring and ingest tests

## Local model development

For Ollama-backed work, set:

```bash
BEN0_MODEL_ADAPTER=ollama
BEN0_OLLAMA_URL=http://localhost:11434
BEN0_OLLAMA_MODEL=gemma3:12b
```
