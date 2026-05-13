from __future__ import annotations

from pathlib import Path

from ben0 import config
from ben0.compilation.codex import CodexEntry
from ben0.compilation.compiler import CodexCompiler
from ben0.compilation.prompts import ExtractionTopic
from ben0.db.models import Document
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.retrieval.index import _iter_codex_entries, build_index
from ben0.retrieval.search import search_index


class MockCompilerAdapter:
    @property
    def model_name(self) -> str:
        return "mock-compiler"

    def generate(self, prompt: str, system: str | None = None) -> str:
        del prompt, system
        return (
            "Definition\n"
            "Status codes describe collection states and cite chunk evidence.\n\n"
            "Current Working Rule\n"
            "Treat living and propagated states as active unless a chunk says otherwise.\n\n"
            "Known Exceptions\n"
            "Legacy records may mix lifecycle and propagation wording.\n\n"
            "Do Not Infer\n"
            "Do not infer current vitality from a historic note alone."
        )


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return db_url, get_session(db_url)


def _topic() -> ExtractionTopic:
    return ExtractionTopic(
        topic_id="status-code-ontology",
        title="Status Code Ontology",
        domain="schema",
        search_queries=["status codes", "life status"],
        extraction_prompt=(
            "Use the evidence below.\n\n"
            "{evidence}\n\n"
            "Respond with Definition, Current Working Rule, Known Exceptions, Do Not Infer."
        ),
    )


def test_codex_entry_markdown_round_trip(tmp_path: Path):
    path = tmp_path / "entry.md"
    entry = CodexEntry(
        topic_id="irisbg-status-codes",
        title="IrisBG Status Codes",
        domain="schema",
        definition="Defines collection status values.",
        working_rule="Use living values as active.",
        known_exceptions="Legacy imports may be inconsistent.",
        do_not_infer="Do not infer availability.",
        source_evidence=[{"chunk_id": "doc:1:0", "summary": "Lists living/dead codes."}],
        generated_by="mock",
        generated_on="2026-05-12",
        review_status="approved",
        pinned=True,
    )

    path.write_text(entry.to_markdown(), encoding="utf-8")
    restored = CodexEntry.from_markdown(path)

    assert restored == entry


def test_codex_entry_is_pinned(tmp_path: Path):
    pinned_path = tmp_path / "pinned.md"
    unpinned_path = tmp_path / "unpinned.md"

    pinned_path.write_text(
        "---\npinned: true\nsource_chunk_ids: []\n---\n\n## Definition\nTest\n",
        encoding="utf-8",
    )
    unpinned_path.write_text(
        "---\npinned: false\nsource_chunk_ids: []\n---\n\n## Definition\nTest\n",
        encoding="utf-8",
    )

    assert CodexEntry.is_pinned(pinned_path) is True
    assert CodexEntry.is_pinned(unpinned_path) is False


def test_compiler_compile_topic_with_mock_adapter(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "compile-topic.db")
    codex_dir = tmp_path / "codex"
    try:
        session.add(
            Document(
                filename="status.txt",
                document_type="policy",
                title="Status",
                full_text=(
                    "Status codes include living, dead, removed, and propagation stages. "
                    "Propagation status tracks sowing, germination, and establishment."
                ),
                character_count=150,
            )
        )
        session.commit()
        build_index(session)

        compiler = CodexCompiler(
            adapter=MockCompilerAdapter(),
            session_factory=lambda: get_session(db_url),
            codex_dir=codex_dir,
        )
        entry = compiler.compile_topic(_topic())

        assert entry is not None
        assert entry.topic_id == "status-code-ontology"
        assert entry.generated_by == "mock-compiler"
        assert (codex_dir / "status-code-ontology.md").exists()
    finally:
        session.close()
        reset_singletons()


def test_compiler_compile_all_skips_pinned_entries(tmp_path: Path):
    codex_dir = tmp_path / "codex"
    codex_dir.mkdir()
    existing = CodexEntry(
        topic_id="status-code-ontology",
        title="Status Code Ontology",
        domain="schema",
        definition="Pinned",
        working_rule="Pinned",
        known_exceptions="Pinned",
        do_not_infer="Pinned",
        source_evidence=[],
        generated_by="human",
        generated_on="2026-05-12",
        review_status="approved",
        pinned=True,
    )
    (codex_dir / "status-code-ontology.md").write_text(existing.to_markdown(), encoding="utf-8")

    compiler = CodexCompiler(adapter=MockCompilerAdapter(), session_factory=lambda: None, codex_dir=codex_dir)
    result = compiler.compile_all([_topic()])

    assert result.compiled == []
    assert result.skipped_pinned == ["status-code-ontology"]


def test_gather_evidence_deduplicates_chunks(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "compile-evidence.db")
    try:
        session.add(
            Document(
                filename="status.txt",
                document_type="policy",
                title="Status",
                full_text=(
                    "Status codes include living, dead, removed, and propagation stages. "
                    "Status codes include living, dead, removed, and propagation stages."
                ),
                character_count=150,
            )
        )
        session.commit()
        build_index(session)

        compiler = CodexCompiler(
            adapter=MockCompilerAdapter(),
            session_factory=lambda: get_session(db_url),
            codex_dir=tmp_path / "codex",
            max_chunks_per_topic=10,
        )
        evidence = compiler._gather_evidence(_topic())

        assert evidence
        assert len(compiler._last_evidence_rows) == 1
        assert compiler._last_evidence_rows[0]["chunk_id"].startswith("doc:")
    finally:
        session.close()
        reset_singletons()


def test_iter_codex_entries_yields_lane_b_generated_entries(tmp_path: Path):
    codex_dir = tmp_path / "codex"
    codex_dir.mkdir()
    entry = CodexEntry(
        topic_id="taxonomic-coverage",
        title="Taxonomic Coverage",
        domain="collection_profile",
        definition="Collection spans multiple families.",
        working_rule="Use codex as generated context.",
        known_exceptions="May lag latest ingest.",
        do_not_infer="Do not infer completeness.",
        source_evidence=[{"chunk_id": "doc:1:0", "summary": "Coverage summary."}],
        generated_by="mock",
        generated_on="2026-05-12",
        review_status="unreviewed",
        pinned=False,
    )
    (codex_dir / "taxonomic-coverage.md").write_text(entry.to_markdown(), encoding="utf-8")

    rows = list(_iter_codex_entries(codex_dir))

    assert rows
    assert rows[0].source_type == "codex_entry"
    assert rows[0].lane == "B"
    assert rows[0].reliability_tier == "generated"
    assert rows[0].document_type == "codex"
    assert rows[0].document_name == "codex:taxonomic-coverage"


def test_build_index_includes_codex_entries(tmp_path: Path, monkeypatch):
    garden_root = tmp_path / "garden"
    (garden_root / "data" / "codex").mkdir(parents=True)
    entry = CodexEntry(
        topic_id="provenance-categories",
        title="Provenance Categories",
        domain="schema",
        definition="Wild, garden, and unknown origin categories are used.",
        working_rule="Use provenance categories cautiously.",
        known_exceptions="Legacy records may be mixed.",
        do_not_infer="Do not infer wild origin from missing data.",
        source_evidence=[{"chunk_id": "doc:2:0", "summary": "Origin categories note."}],
        generated_by="mock",
        generated_on="2026-05-12",
        review_status="unreviewed",
        pinned=False,
    )
    (garden_root / "data" / "codex" / "provenance-categories.md").write_text(entry.to_markdown(), encoding="utf-8")

    db_url, session = _session_for(tmp_path, "codex-index.db")
    monkeypatch.setattr(config, "_GARDEN_ROOT", garden_root)
    try:
        count = build_index(session)
        results = search_index(session, "wild origin categories", limit=5, lane="B")

        assert count > 0
        assert results
        assert results[0]["lane"] == "B"
        assert results[0]["reliability_tier"] == "generated"
        assert results[0]["document_type"] == "codex"
    finally:
        session.close()
        reset_singletons()
