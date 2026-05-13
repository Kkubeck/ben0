# BEN-0

BEN-0 (Botanical Engram Node) is a local-first botanical garden collection stewardship tool. It combines deterministic data validation, document indexing, lightweight retrieval, correction tickets, and a cautious “visiting scholar” assistant that helps staff interpret records without taking authority away from curators.

The core idea is simple: keep institutional memory close to the collection, keep human authority intact, and make messy accession data easier to trust, review, and improve.

## Why “visiting scholar”?

BEN-0 is designed to behave like a careful in-house research assistant, not an autonomous editor. It can surface evidence, point to likely problems, draft tickets, and summarize what the records suggest. It does **not** silently rewrite collection data or pretend uncertainty is certainty.

## Features

- Local SQLite database with SQLAlchemy models
- Synthetic dataset generator for demos and testing
- Synthetic CSV ingest plus IrisBG export ingest
- Text and PDF document ingest with local retrieval
- Deterministic validation engine for data quality checks
- Correction ticket workflow
- Markdown reporting and Streamlit dashboard
- Local assistant with mock, Gemma, Qwen, and Ollama-backed adapters
- Three-lane hybrid RAG with codex compilation, rules, and evidence checks
- Institution interview workflow for capturing local garden rules and quirks
- Garden workspaces plus saved/resumable sessions
- Sensitive-data-aware export path

## Quick start

### 1. Create a virtual environment

**Windows (Git Bash)**

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

### 2. Generate synthetic demo data

```bash
ben0 generate
```

This writes a fictional collection dataset to `data/synthetic/`.

### 3. Run the full synthetic pipeline

```bash
ben0 init-db
ben0 ingest --data-dir data/synthetic --format synthetic
ben0 validate
ben0 index
ben0 report
```

Optional:

```bash
ben0 search provenance
ben0 tickets create-from-issues
ben0 dashboard
ben0 ask "which accessions have missing provenance?"
```

## UBCBG / IrisBG deployment guide

BEN-0 can ingest paired IrisBG exports directly.

### Expected files

Put these in `data/raw/` (or another directory you pass to `--data-dir`):

- `accession_history.csv`
- `accession_item_history.csv`

### Setup

1. Copy `.env.example` to `.env`
2. Adjust database and institution values as needed
3. For a UBCBG deployment, uncomment or set:

```bash
BEN0_INSTITUTION_NAME=UBC Botanical Garden
BEN0_INSTITUTION_CODE=UBC
```

### Run

```bash
ben0 init-db
ben0 ingest --data-dir data/raw --format iris
ben0 validate
ben0 index
ben0 report --output data/exports/ubcbg_health_report.md
```

If you leave `--format` at the default `auto`, BEN-0 will detect IrisBG input when it sees `accession_history.csv`.

## Ollama / Gemma setup

BEN-0 ships with a deterministic mock adapter, but it can also use a local Ollama model.

### Install and pull a model

```bash
ollama serve
ollama pull gemma3:12b
```

### Configure `.env`

```bash
BEN0_MODEL_ADAPTER=ollama
BEN0_OLLAMA_URL=http://localhost:11434
BEN0_OLLAMA_MODEL=gemma3:12b
```

### Ask BEN-0 a question

```bash
ben0 ask "summarize the collection overview"
```

## RAG Architecture

BEN-0 now uses a three-lane hybrid RAG design:

- **Lane A: source retrieval** — raw documents, notes, and database-derived text with provenance metadata
- **Lane B: compiled codex** — generated topic summaries and working interpretations derived from Lane A
- **Lane C: rules layer** — structured YAML rules, mappings, and local exceptions injected as authoritative constraints

At answer time, BEN-0 combines retrieval from raw sources and compiled codex content, applies matched rule files, then runs evidence/conflict checks before returning a response. This keeps the original source material as the court of appeal while still giving the model useful domain structure.

BEN-0 also includes an **institution interview** flow (`ben0 interview`) that asks eight data-informed setup questions about statuses, provenance, workflow, locations, collection focus, known data quirks, and sensitive data handling. Answers are parsed into Lane C rule files and can be resumed, reviewed, or rerun later.

## CLI reference

### Core setup

- `ben0 init-db` — create tables
- `ben0 generate` — build the synthetic dataset
- `ben0 ingest --data-dir <dir> [--format auto|synthetic|iris]` — load structured data and documents
- `ben0 init --garden <name>` — create a garden workspace
- `ben0 use <garden>` — switch active garden workspace
- `ben0 gardens` — list configured garden workspaces
- `ben0 sessions` — list saved chat/interview sessions

Examples:

```bash
ben0 ingest --data-dir data/synthetic --format synthetic
ben0 ingest --data-dir data/raw --format iris
```

### Data quality and retrieval

- `ben0 validate` — run deterministic validation rules
- `ben0 index` — build the local retrieval index
- `ben0 search "<query>" --limit 5` — query indexed text
- `ben0 report [--output path]` — generate a Markdown health report
- `ben0 dashboard --port 8501` — launch Streamlit dashboard

### Tickets and export

- `ben0 tickets` — list correction tickets
- `ben0 tickets create-from-issues` — create review tickets from open issues
- `ben0 export --output data/exports/accessions.json` — export accession records
- `ben0 export --include-sensitive` — include restricted/review-only records

### Assistant

- `ben0 ask "<question>"` — single-turn Q&A
- `ben0 chat` — interactive chat loop
- `ben0 ask|chat --model gemma|qwen|mock|ollama` — switch runtime model per command

### RAG and knowledge tools

- `ben0 seed-rules` — inspect or install seed rule files
- `ben0 rules` — inspect active rule files and matches
- `ben0 compile` — build/update codex entries from source material
- `ben0 codex` — inspect compiled codex entries
- `ben0 interview` — run or resume the institution interview
- `ben0 search "<query>" [--skip-vectors|--vectors-only]` — control hybrid retrieval behavior
- `ben0 ask|chat --critic` — enable the optional LLM critic/evidence pass

## Architecture overview

- `ben0.db` — ORM models and session management
- `ben0.synthetic` — fictional demo dataset generator with deliberate data-quality problems
- `ben0.ingest` — CSV/document loaders, normalization helpers, and the IrisBG adapter
- `ben0.validation` — deterministic rules and persistence of validation issues
- `ben0.retrieval` — chunking, FTS5 indexing, and local search
- `ben0.tickets` — correction ticket creation and listing helpers
- `ben0.reports` — Markdown health report generation
- `ben0.dashboard` — collection metrics and Streamlit interface
- `ben0.assistant` — visiting scholar persona, tool registry, orchestration, and model adapters
- `ben0.export` — filtered JSON export for downstream sharing

## Running tests

```bash
pytest -v
```

Or from a fresh editable install:

```bash
python -m pytest -v
```

## Platform support

BEN-0 is designed to work on:

- Windows (recommended shell: **Git Bash**)
- macOS
- Linux

SQLite keeps setup lightweight, and the default stack works well on a laptop with a Python virtual environment. Ollama support makes it possible to keep the assistant local as well.

## Project status

This is a prototype meant to make botanical collection stewardship more legible, reviewable, and locally deployable. It is intentionally conservative: deterministic first, human-reviewed where it matters, model-agnostic where useful.
