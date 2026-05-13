"""BEN-0 CLI interface."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import click


@click.group()
def cli():
    """BEN-0: Botanical collection data management and curation toolkit.

    Manages botanical garden accessions, herbarium specimens, living collections,
    taxonomic data, and conservation status tracking. Provides data validation,
    search capabilities, collection health reporting, and AI-powered botanical
    collection insights through natural language queries.

    Start with: ben0 init --garden "Your Garden Name"
    Then: ben0 generate && ben0 ingest && ben0 validate && ben0 index
    """
    pass


@cli.command()
@click.option("--garden", default=None, help="Create a new garden workspace with this name")
def init(garden):
    """Initialize database schema or create a new garden workspace.

    Sets up the database tables for botanical collection management. Without
    --garden, initializes the schema for the current garden. With --garden,
    creates a new workspace and activates it.

    Examples:
        ben0 init
        ben0 init --garden "UBC Botanical Garden"
        ben0 init --garden "Royal Botanic Garden Edinburgh"
        ben0 init --garden "Kew Gardens Conservation Unit"
    """
    from ben0 import config
    from ben0.db.session import init_db as _init_db

    if garden:
        # Create new garden workspace
        garden_root = config.create_garden(garden)
        click.echo(f"Created garden workspace '{garden}' at {garden_root}")

        # Set it as active
        config.set_active_garden(garden)
        click.echo(f"Activated garden '{garden}'")

        # Reset singletons to use new garden paths
        config.reset_singletons()

        # Initialize database for the new garden
        _init_db()
        click.echo(f"Database initialized for garden '{garden}'.")
    else:
        # Legacy init-db behavior
        _init_db()
        active_garden = config.get_active_garden()
        if active_garden:
            click.echo(f"Database initialized for garden '{active_garden}'.")
        else:
            click.echo("Database initialized.")


@cli.command()
def init_db():
    """Initialize the database schema for botanical collections.

    Creates all tables needed for accession tracking, taxon management,
    propagation records, and conservation status monitoring. Safe to run
    multiple times — existing data is preserved.

    Examples:
        ben0 init-db
        # Run after switching gardens to ensure schema is current
        ben0 use "Herbarium Collection" && ben0 init-db
    """
    from ben0.db.session import init_db as _init_db

    _init_db()
    click.echo("Database initialized.")


@cli.command()
@click.argument("garden_name")
def use(garden_name):
    """Switch active garden workspace for subsequent botanical data operations.

    Changes the active garden to GARDEN_NAME. All subsequent commands
    will operate on that garden's data until changed again.

    Arguments:
        GARDEN_NAME  Name of the garden workspace to activate.

    Examples:
        ben0 use "UBC Botanical Garden"
        ben0 use "Herbarium Collection"
        ben0 use "Seed Bank Accessions"
        ben0 use RBGE  # Short form for Royal Botanic Garden Edinburgh
    """
    from ben0 import config

    try:
        config.set_active_garden(garden_name)
        config.reset_singletons()
        click.echo(f"Switched to garden '{garden_name}'")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("Use 'ben0 gardens' to see available gardens.")
        sys.exit(1)


@cli.command()
def gardens():
    """List all available garden workspaces and show the active one.

    Shows all garden workspaces with the currently active one marked with *.
    Each garden workspace maintains its own botanical collection database
    and configuration settings.

    Examples:
        ben0 gardens  # View all workspaces
        # Sample output:
        #   * UBC Botanical Garden (current)
        #     Royal Botanic Garden Edinburgh
        #     Kew Gardens Conservation Unit
    """
    from ben0 import config

    available_gardens = config.list_gardens()
    active_garden = config.get_active_garden()

    if not available_gardens:
        if active_garden:
            click.echo("No garden workspaces found, but there is an active garden:")
            click.echo(f"  * {active_garden} (current)")
        else:
            click.echo("No garden workspaces found.")
            click.echo("Create one with: ben0 init --garden \"Garden Name\"")
        return

    click.echo("Available gardens:")
    for garden in available_gardens:
        marker = " *" if garden == active_garden else "  "
        click.echo(f"{marker} {garden}")

    if not active_garden:
        click.echo("\nNo active garden. Use 'ben0 use <name>' to activate one.")


@cli.command()
@click.option("--count", default=300, show_default=True, help="Number of accessions to generate.")
def generate(count):
    """Generate synthetic botanical collection data for testing.

    Creates realistic CSV datasets including taxonomic hierarchies, accession
    records with provenance data, living collection items, propagation events,
    and OCR-scanned accession cards. Includes conservation-status taxa and
    wild-collection localities.

    Examples:
        ben0 generate
        ben0 generate --count 500  # Medium herbarium collection
        ben0 generate --count 2000 # Large botanical garden dataset
    """
    from ben0 import config
    from ben0.synthetic.generate_dataset import generate_all

    generate_all(config.SYNTHETIC_DIR, count=count)


@cli.command()
@click.option("--data-dir", default=None, help="Path to data directory")
@click.option(
    "--format",
    "ingest_format",
    type=click.Choice(["auto", "synthetic", "iris"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Input dataset format.",
)
def ingest(data_dir, ingest_format):
    """Ingest botanical collection data from CSV files and documents.

    Imports accession records, taxonomic data, living collection items,
    provenance information, and supporting documents. Auto-detects IrisBG
    export format or BEN-0 synthetic datasets. Creates database schema if needed.

    Examples:
        ben0 ingest  # Import synthetic test data
        ben0 ingest --data-dir ./herbarium_exports --format iris
        ben0 ingest --data-dir /mnt/collection_data/2024_census
        ben0 ingest --data-dir ./seed_bank_accessions --format synthetic
    """
    from ben0 import config
    from ben0.db.session import init_db as _init_db
    from ben0.ingest.csv_ingest import ingest_all_csvs
    from ben0.ingest.document_ingest import ingest_documents
    from ben0.ingest.iris_ingest import ingest_iris_csvs

    def _resolve_format(base_dir: Path, requested: str) -> str:
        requested = requested.lower()
        if requested != "auto":
            return requested
        if (base_dir / "accession_history.csv").exists():
            return "iris"
        if (base_dir / "accessions.csv").exists():
            return "synthetic"
        raise click.ClickException(
            "Could not auto-detect dataset format. Expected accession_history.csv or accessions.csv."
        )

    _init_db()

    source_dir = Path(data_dir) if data_dir else config.SYNTHETIC_DIR
    resolved_format = _resolve_format(source_dir, ingest_format)
    ingest_fn = ingest_iris_csvs if resolved_format == "iris" else ingest_all_csvs

    click.echo(f"Ingesting {resolved_format} data from {source_dir}...")
    counts = ingest_fn(source_dir)
    for table, n in counts.items():
        click.echo(f"  {table}: {n} rows")

    doc_dir = source_dir / "documents"
    if doc_dir.exists():
        doc_counts = ingest_documents(doc_dir)
        for table, n in doc_counts.items():
            click.echo(f"  {table}: {n} records")

    click.echo("Ingestion complete.")


@cli.command(name="validate")
@click.option("--append/--clear", default=False, help="Append issues instead of replacing them.")
def validate_command(append):
    """Run data quality validation on botanical collection records.

    Detects duplicate accession numbers, orphaned living collection items,
    invalid collection dates, missing provenance data, taxonomic name conflicts,
    and conservation status inconsistencies. Issues are categorized by severity.

    Examples:
        ben0 validate  # Clean validation of all collection data
        ben0 validate --append  # Add new issues after recent data imports
        # Typical workflow: ingest → validate → review issues → create tickets
    """
    from ben0.db.session import get_session, init_db as _init_db
    from ben0.validation.engine import run_validation

    _init_db()
    session = get_session()
    try:
        summary = run_validation(session, clear_existing=not append)
    finally:
        session.close()

    click.echo("Validation complete.")
    for key in ("critical", "error", "warning", "info", "total"):
        if key in summary:
            click.echo(f"  {key}: {summary[key]}")


@cli.command(name="index")
@click.option("--skip-vectors", is_flag=True, help="Skip LanceDB vector index rebuild.")
@click.option("--vectors-only", is_flag=True, help="Only rebuild the LanceDB vector index.")
def index_command(skip_vectors, vectors_only):
    """Build full-text search index for botanical collection data.

    Creates searchable text chunks from accession records, taxonomic names,
    collection localities, propagation notes, and document content. Enables
    fast retrieval of specimens, taxa, and conservation information.

    Examples:
        ben0 index  # Rebuild complete search index
        # Run after data imports: ingest → validate → index → search
        # Required before using 'ben0 search' or 'ben0 ask' commands
    """
    from ben0 import config
    from ben0.db.session import get_session, init_db as _init_db
    from ben0.retrieval.index import build_index

    if skip_vectors and vectors_only:
        raise click.ClickException("--skip-vectors and --vectors-only cannot be used together.")

    _init_db()
    session = get_session()
    try:
        if not vectors_only:
            started = time.perf_counter()
            fts_count = build_index(session)
            click.echo(f"FTS5 index: {fts_count} entries ({time.perf_counter() - started:.1f}s)")

        if not skip_vectors:
            try:
                from ben0.retrieval.vector_index import build_vector_index
            except ImportError:
                click.echo(
                    "Warning: vector dependencies unavailable; skipping vector index. "
                    "Install with `pip install ben0[vectors]`.",
                    err=True,
                )
            else:
                started = time.perf_counter()
                vector_count = build_vector_index(session, config._GARDEN_ROOT / "data" / "vector")
                click.echo(f"Vector index: {vector_count} entries ({time.perf_counter() - started:.1f}s)")
    finally:
        session.close()


@cli.command(name="seed-rules")
def seed_rules_command():
    """Seed authoritative rule files into the active garden workspace."""
    from ben0 import config
    from ben0.rules.loader import seed_rules

    target_dir = config._GARDEN_ROOT / "data" / "rules"
    seeded = seed_rules(target_dir)
    click.echo(f"Seeded {seeded} rule file(s) into {target_dir}.")


@cli.command(name="rules")
def rules_command():
    """List authoritative rule files for the active garden workspace."""
    from ben0 import config
    from ben0.rules.loader import load_rules

    rules_dir = config._GARDEN_ROOT / "data" / "rules"
    rules = load_rules(rules_dir)

    if not rules:
        click.echo(f"No rule files found in {rules_dir}.")
        return

    for rule in rules:
        pinned = "yes" if rule.pinned else "no"
        click.echo(
            f"{rule.id}: {rule.name} | tags={len(rule.tags)} | pinned={pinned} | priority={rule.priority}"
        )


@cli.command(name="compile")
@click.option("--topic", default=None, help="Compile only a specific codex topic id.")
@click.option("--force", is_flag=True, help="Recompile even if an existing codex entry is pinned.")
@click.option(
    "--model",
    type=click.Choice(["mock", "gemma", "qwen", "ollama"], case_sensitive=False),
    default=None,
    help="Model adapter to use for codex compilation.",
)
def compile_command(topic, force, model):
    """Compile Lane B codex entries from Lane A retrieval evidence."""
    from ben0 import config
    from ben0.assistant.orchestrator import _build_default_adapter
    from ben0.compilation.compiler import CodexCompiler
    from ben0.compilation.prompts import DEFAULT_TOPICS
    from ben0.db.session import get_session, init_db as _init_db

    _init_db()
    topics = DEFAULT_TOPICS
    if topic:
        topics = [item for item in DEFAULT_TOPICS if item.topic_id == topic]
        if not topics:
            raise click.ClickException(f"Unknown codex topic: {topic}")

    compiler = CodexCompiler(
        adapter=_build_model_adapter(model) if model else _build_default_adapter(),
        session_factory=get_session,
        codex_dir=config._GARDEN_ROOT / "data" / "codex",
    )
    result = compiler.compile_all(topics, force=force)

    click.echo(f"Compiled {len(result.compiled)} topic(s).")
    click.echo(f"Skipped pinned: {len(result.skipped_pinned)}")
    click.echo(f"Skipped no evidence: {len(result.skipped_no_evidence)}")
    click.echo(f"Errors: {len(result.errors)}")
    for topic_id, message in result.errors:
        click.echo(f"  {topic_id}: {message}")


@cli.command(name="codex")
def codex_command():
    """List compiled codex entries in the active garden workspace."""
    from ben0 import config
    from ben0.compilation.codex import CodexEntry

    codex_dir = config._GARDEN_ROOT / "data" / "codex"
    entries = []
    if codex_dir.exists():
        for path in sorted(codex_dir.glob("*.md")):
            try:
                entries.append(CodexEntry.from_markdown(path))
            except Exception:
                continue

    if not entries:
        click.echo("No codex entries found. Run 'ben0 compile' to generate them.")
        return

    for entry in entries:
        pinned = "yes" if entry.pinned else "no"
        click.echo(
            f"{entry.topic_id}: {entry.title} | domain={entry.domain} | review_status={entry.review_status} | pinned={pinned}"
        )


@cli.command(name="search")
@click.argument("query")
@click.option("--limit", default=5, show_default=True, help="Maximum number of matches.")
def search_command(query, limit):
    """Search botanical collection data using full-text queries.

    Runs a full-text query against the indexed collection data and returns
    matching chunks with linked accession, item, and taxon references. Search
    across taxonomic names, localities, propagation notes, and document content.

    Arguments:
        QUERY  The search terms to look for.

    Options:
        --limit  Maximum number of results to return (default: 5).

    Examples:
        ben0 search "Calypso bulbosa"  # Find fairy slipper orchid records
        ben0 search "nursery propagation" --limit 10
        ben0 search "endangered Pacific coast"  # Conservation status + locality
        ben0 search "Acer macrophyllum seed collection"  # Bigleaf maple seeds
    """
    from ben0.db.session import get_session
    from ben0.retrieval.search import search_index

    session = get_session()
    try:
        results = search_index(session, query, limit=limit)
    finally:
        session.close()

    if not results:
        click.echo("No results.")
        return

    for idx, result in enumerate(results, start=1):
        click.echo(f"[{idx}] {result['document_name']} ({result['chunk_id']})")
        click.echo(f"    {result['snippet']}")
        click.echo(
            "    links: "
            f"accession={result.get('accession_id') or '-'} "
            f"item={result.get('item_id') or '-'} taxon={result.get('taxon_id') or '-'}"
        )


@cli.group(name="tickets", invoke_without_command=True)
@click.pass_context
@click.option("--status", default=None, help="Filter by ticket status.")
@click.option("--entity-type", default=None, help="Filter by affected entity type.")
def tickets_group(ctx, status, entity_type):
    """List and manage data correction tickets for collection issues.

    Displays actionable tickets for fixing duplicate accessions, updating
    taxonomic names, correcting provenance data, and resolving conservation
    status conflicts. Created from validation issues.

    Examples:
        ben0 tickets  # List all data correction tickets
        ben0 tickets --status open  # Show pending collection issues
        ben0 tickets --entity-type accession  # Accession-specific problems
        ben0 tickets --entity-type taxon  # Taxonomic name conflicts
    """
    if ctx.invoked_subcommand:
        return

    from ben0.db.session import get_session
    from ben0.tickets.service import list_tickets

    session = get_session()
    try:
        tickets = list_tickets(session, status=status, entity_type=entity_type)
    finally:
        session.close()

    if not tickets:
        click.echo("No tickets found.")
        return

    for ticket in tickets:
        click.echo(f"- {ticket.id}: {ticket.title} [{ticket.status}/{ticket.confidence}]")


@tickets_group.command(name="create-from-issues")
@click.option("--status", default="open", show_default=True, help="Validation issue status to convert.")
def tickets_create_from_issues(status):
    """Convert validation issues into actionable correction tickets.

    Transforms data quality problems (duplicate accessions, invalid taxa,
    missing provenance) into trackable work items for collection managers.
    Prevents duplicate tickets for the same underlying issue.

    Examples:
        ben0 tickets create-from-issues  # Convert all open validation issues
        ben0 tickets create-from-issues --status critical  # Priority fixes only
        ben0 tickets create-from-issues --status error  # Structural problems
    """
    from ben0.db.session import get_session
    from ben0.tickets.service import create_tickets_from_issues

    session = get_session()
    try:
        tickets = create_tickets_from_issues(session, status=status)
    finally:
        session.close()

    click.echo(f"Created or reused {len(tickets)} tickets.")


@cli.command(name="export")
@click.option("--output", default=None, help="Path to JSON export file.")
@click.option("--include-sensitive", is_flag=True, help="Include restricted or review-only records.")
def export_command(output, include_sensitive):
    """Export botanical collection records to JSON with data sensitivity controls.

    Creates shareable datasets for research collaboration while protecting
    sensitive locality data for rare or endangered species. Follows CDBG
    data sharing guidelines for conservation-listed taxa.

    Examples:
        ben0 export  # Public-safe export with sensitive localities redacted
        ben0 export --output herbarium_share_2024.json
        ben0 export --include-sensitive --output internal_research.json
        ben0 export --output gbif_upload.json  # For biodiversity portals
    """
    from ben0 import config
    from ben0.db.session import get_session
    from ben0.export.basic_export import export_accessions

    output_path = Path(output) if output else config.EXPORTS_DIR / "accessions_export.json"
    session = get_session()
    try:
        summary = export_accessions(session, output_path, include_sensitive=include_sensitive)
    finally:
        session.close()

    click.echo(
        f"Exported {summary['exported']} records to {summary['path']} "
        f"(skipped {summary['skipped']})."
    )


@cli.command(name="report")
@click.option("--output", default=None, help="Write the Markdown report to a file instead of stdout.")
def report_command(output):
    """Generate comprehensive botanical collection health assessment report.

    Creates detailed Markdown report covering taxonomic diversity, accession
    completeness, conservation status coverage, geographic representation,
    data quality metrics, and curation priorities.

    Examples:
        ben0 report  # Display collection summary to terminal
        ben0 report --output annual_report_2024.md
        ben0 report --output collection_audit.md  # For management review
        ben0 report --output conservation_status.md  # For grant applications
    """
    from ben0.db.session import get_session
    from ben0.reports.markdown_report import generate_markdown_report

    session = get_session()
    try:
        report = generate_markdown_report(session, output_path=output)
    finally:
        session.close()

    if output:
        click.echo(f"Report written to {output}")
    else:
        click.echo(report)


@cli.command(name="dashboard")
@click.option("--port", default=8501, show_default=True, help="Streamlit server port.")
def dashboard_command(port):
    """Launch interactive web dashboard for collection visualization.

    Opens Streamlit interface showing taxonomic diversity charts, geographic
    distribution maps, conservation status summaries, data quality metrics,
    and curation workflow tracking for botanical collections.

    Examples:
        ben0 dashboard  # Launch at http://localhost:8501
        ben0 dashboard --port 9000  # Custom port for team sharing
        # Access via browser for interactive collection analytics
    """
    from ben0.dashboard.app import APP_PATH

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            APP_PATH,
            "--server.port",
            str(port),
        ],
        check=True,
    )


def _build_model_adapter(model_choice):
    """Build the appropriate model adapter based on user choice."""
    from ben0.assistant.model_adapters import MockModelAdapter, OllamaAdapter, OpenAICompatibleAdapter
    from ben0 import config

    if model_choice == "mock":
        return MockModelAdapter()
    elif model_choice == "gemma":
        return OllamaAdapter(model="gemma3:12b")
    elif model_choice == "qwen":
        return OllamaAdapter(model="qwen3:8b")
    elif model_choice == "ollama":
        return OllamaAdapter()
    else:
        # Default behavior - use config to determine adapter
        return None


@cli.command(name="interview")
@click.option(
    "--model",
    type=click.Choice(["mock", "gemma", "qwen", "ollama"], case_sensitive=False),
    default=None,
    help="Model adapter to use for interview rule parsing.",
)
@click.option("--reset", is_flag=True, help="Reset saved interview state and start over.")
@click.option("--status", "status_only", is_flag=True, help="Show interview progress without running it.")
def interview_command(model, reset, status_only):
    """Run or inspect the institution interview for the active garden."""
    from ben0 import config
    from ben0.assistant.orchestrator import _build_default_adapter
    from ben0.db.session import get_session, init_db as _init_db
    from ben0.interview.conductor import InterviewConductor
    from ben0.interview.questions import DEFAULT_QUESTIONS
    from ben0.interview.session import InterviewSession

    _init_db()
    garden_name = config.get_active_garden() or config.INSTITUTION_NAME
    state_path = config._GARDEN_ROOT / "data" / "interview_state.json"
    rules_dir = config._GARDEN_ROOT / "data" / "rules"
    state_manager = InterviewSession(state_path, DEFAULT_QUESTIONS)
    state = state_manager.load_or_create(garden_name)

    if reset:
        state_manager.reset(state)
        state_manager.save(state)
        click.echo("Interview state reset.")

    if status_only:
        total = len(DEFAULT_QUESTIONS)
        answered = len(state.completed_questions)
        skipped = len(state.skipped_questions)
        remaining = total - answered - skipped
        click.echo(f"Interview status for {state.garden_name}:")
        click.echo(f"  answered: {answered}/{total}")
        click.echo(f"  skipped: {skipped}")
        click.echo(f"  remaining: {remaining}")
        if state.current_question:
            click.echo(f"  current_question: {state.current_question}")
        return

    adapter = _build_model_adapter(model) if model else _build_default_adapter()
    conductor = InterviewConductor(
        adapter=adapter,
        session_factory=get_session,
        rules_dir=rules_dir,
        state_path=state_path,
        garden_name=garden_name,
    )
    conductor.run()


@cli.command(name="ask")
@click.argument("question")
@click.option(
    "--model",
    type=click.Choice(["mock", "gemma", "qwen", "ollama"], case_sensitive=False),
    default=None,
    help="Model adapter to use for this query."
)
@click.option("--critic", is_flag=True, help="Run an extra model-based critique pass on the final answer.")
def ask_command(question, model, critic):
    """Query the botanical collection assistant with natural language questions.

    Sends QUESTION to the BEN-0 assistant and prints the answer. The
    assistant has access to all ingested collection data, taxonomic information,
    and documents to provide comprehensive responses about your botanical collection.

    Arguments:
        QUESTION  The question to ask (quote multi-word queries).

    Examples:
        ben0 ask "How many accessions lack provenance data?"
        ben0 ask --model gemma "How many accessions lack provenance?"
        ben0 ask --model qwen "What conservation-listed taxa are in the collection?"
        ben0 ask "Which Quercus species need propagation attention?"
        ben0 ask "Show me recent seed collections from endangered populations"
        ben0 ask "What's the geographic distribution of our fern collection?"
    """
    from ben0.assistant.orchestrator import AssistantOrchestrator

    adapter = _build_model_adapter(model)
    orchestrator = AssistantOrchestrator(adapter=adapter, enable_critic=critic)
    click.echo(orchestrator.answer(question))


@cli.command(name="chat")
@click.option(
    "--model",
    type=click.Choice(["mock", "gemma", "qwen", "ollama"], case_sensitive=False),
    default=None,
    help="Model adapter to use for this chat session."
)
@click.option(
    "--session",
    default=None,
    help="Session name to resume or create."
)
@click.option("--critic", is_flag=True, help="Run an extra model-based critique pass on each final answer.")
def chat_command(model, session, critic):
    """Start interactive chat session with the botanical collection assistant.

    Opens a REPL-style conversation where you can ask multiple questions
    about the collection, explore taxonomic relationships, analyze curation
    priorities, and get collection management insights. Type 'exit' or Ctrl+D to quit.

    Sessions are automatically saved on exit and can be resumed later.

    Examples:
        ben0 chat
        ben0 chat --model gemma
        ben0 chat --session myresearch
        ben0 chat --model qwen --session myresearch
        # Interactive session allows follow-up questions like:
        # > "What taxa need propagation attention?"
        # > "Show details for the Quercus collection"
        # > "Which accessions have missing locality data?"
    """
    from ben0.assistant.orchestrator import AssistantOrchestrator

    adapter = _build_model_adapter(model)
    orchestrator = AssistantOrchestrator(adapter=adapter, enable_critic=critic)
    orchestrator.chat(session_name=session)


@cli.group(name="sessions", invoke_without_command=True)
@click.pass_context
def sessions_group(ctx):
    """List and manage saved conversation sessions.

    Sessions capture conversation history with the BEN-0 assistant, allowing
    you to resume previous conversations or review past work.

    Examples:
        ben0 sessions  # List all saved sessions
        ben0 sessions delete old-session-name
    """
    if ctx.invoked_subcommand:
        return

    from ben0.session import SessionManager

    manager = SessionManager()
    sessions = manager.list_sessions()

    if not sessions:
        click.echo("No saved sessions found.")
        return

    click.echo("Saved sessions:")
    for session in sessions:
        garden_info = f" (garden: {session['garden']})" if session['garden'] else ""
        updated_date = session['updated_at'][:10]  # Just the date part
        click.echo(
            f"  {session['name']} - {session['turn_count']} turns, "
            f"{session['model_adapter']}, updated {updated_date}{garden_info}"
        )


@sessions_group.command(name="delete")
@click.argument("session_name")
def sessions_delete(session_name):
    """Delete a saved conversation session.

    Permanently removes the specified session file from disk.

    Arguments:
        SESSION_NAME  Name of the session to delete.

    Examples:
        ben0 sessions delete old-research
        ben0 sessions delete session-2026-05-06-1
    """
    from ben0.session import SessionManager

    manager = SessionManager()
    if manager.delete_session(session_name):
        click.echo(f"Deleted session '{session_name}'")
    else:
        click.echo(f"Session '{session_name}' not found", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
