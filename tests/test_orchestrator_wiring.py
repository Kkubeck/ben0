"""Tests for orchestrator wiring of entity detection and dossiers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ben0.assistant.model_adapters import MockModelAdapter
from ben0.assistant.orchestrator import AssistantOrchestrator
from ben0.db.models import Accession, Base, Item, Provenance, Taxon
from ben0.memory.dossier import load_dossier
from ben0.session import ConversationTurn


# captured_prompts is a list[str].
# Interpretation: each entry is one prompt sent to the mock adapter.
# Examples:
#   ["Available tools: search_records ..."]
#   ["## Recent conversation\nUser: Tell me more ..."]


class CaptureMockAdapter(MockModelAdapter):
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.prompts.append(prompt)
        self.system_prompts.append(system or "")
        return super().generate(prompt, system=system)


def _make_session_factory(db_path: Path) -> tuple[callable, Session]:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory, factory()


def _seed_entities(session: Session) -> None:
    taxon = Taxon(id="taxon-1", scientific_name="Acer macrophyllum", family="Sapindaceae")
    accession = Accession(
        id="acc-1",
        accession_number="1968-0042",
        accession_number_normalized="1968-0042",
        accession_date="1968-03-15",
        taxon_id="taxon-1",
    )
    item = Item(id="item-1", accession_id="acc-1", life_status="dead")
    provenance = Provenance(id="prov-1", accession_id="acc-1", collector="J. Smith", origin_code="W")
    session.add_all([taxon, accession, item, provenance])
    session.commit()


def _fake_registry(_: Session, adapter: MockModelAdapter | None = None, compression_level: int | None = None) -> dict:
    del adapter, compression_level

    def search_records(query: str) -> dict:
        return {
            "tool": "search_records",
            "accessions": [
                {
                    "id": "acc-1",
                    "accession_number": "1968-0042",
                    "citation": "accession:1968-0042",
                    "taxon": "Acer macrophyllum",
                    "taxon_id": "taxon-1",
                    "accession_year": 1968,
                    "life_status": "dead",
                    "bed_code": "D-42",
                    "collector": "J. Smith",
                    "text": (
                        "Accession 1968-0042 for Acer macrophyllum is dead in bed D-42 "
                        "and was collected by J. Smith."
                    ),
                }
            ],
            "query": query,
        }

    return {"search_records": search_records}


def test_entity_detection_runs_on_question_during_answer(tmp_path: Path) -> None:
    session_factory, seed_session = _make_session_factory(tmp_path / "wiring-detect.db")
    try:
        _seed_entities(seed_session)
    finally:
        seed_session.close()

    orchestrator = AssistantOrchestrator(
        adapter=MockModelAdapter(),
        session_factory=session_factory,
    )

    with patch("ben0.assistant.orchestrator.build_tool_registry", side_effect=_fake_registry):
        with patch("ben0.assistant.orchestrator.detect_entities", wraps=__import__(
            "ben0.assistant.entity_detection", fromlist=["detect_entities"]
        ).detect_entities) as detect_mock:
            orchestrator.answer("Which accession for Acer macrophyllum is dead?")

    asked_questions = [call.args[1] for call in detect_mock.call_args_list]
    assert "Which accession for Acer macrophyllum is dead?" in asked_questions


def test_answer_creates_and_updates_dossiers(tmp_path: Path) -> None:
    session_factory, seed_session = _make_session_factory(tmp_path / "wiring-dossier.db")
    try:
        _seed_entities(seed_session)
    finally:
        seed_session.close()

    orchestrator = AssistantOrchestrator(
        adapter=MockModelAdapter(),
        session_factory=session_factory,
    )

    with patch("ben0.assistant.orchestrator.build_tool_registry", side_effect=_fake_registry):
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path / "dossiers"):
            answer = orchestrator.answer("Which accession for Acer macrophyllum is dead?")
            taxon_dossier = load_dossier("taxon", "taxon-1")
            accession_dossier = load_dossier("accession", "1968-0042")

    assert "1968-0042" in answer
    assert any("Sapindaceae" in fact for fact in taxon_dossier.facts)
    assert any("dead in bed D-42" in entry.text for entry in taxon_dossier.learned)
    assert any(entry.tags == ["status", "location"] for entry in taxon_dossier.learned)
    assert accession_dossier.learned


def test_prompt_includes_recent_conversation_and_entity_context(tmp_path: Path) -> None:
    session_factory, seed_session = _make_session_factory(tmp_path / "wiring-prompt.db")
    try:
        _seed_entities(seed_session)
    finally:
        seed_session.close()

    adapter = CaptureMockAdapter()
    orchestrator = AssistantOrchestrator(
        adapter=adapter,
        session_factory=session_factory,
    )
    orchestrator.current_session = orchestrator.session_manager.create_session(
        name="wiring-prompt",
        model_adapter="mock",
    )
    orchestrator.current_session.turns = [
        ConversationTurn(
            role="user",
            content="Tell me about Acer macrophyllum.",
            timestamp="2026-07-05T00:00:00",
        ),
        ConversationTurn(
            role="assistant",
            content="It is in the collection.",
            timestamp="2026-07-05T00:00:01",
        ),
    ]

    with patch("ben0.assistant.orchestrator.build_tool_registry", side_effect=_fake_registry):
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path / "dossiers"):
            answer = orchestrator.answer("Which accession for Acer macrophyllum is dead?")

    first_prompt = adapter.prompts[0]
    assert "## Recent conversation" in first_prompt
    assert "User: Tell me about Acer macrophyllum." in first_prompt
    assert "## Entity context" in first_prompt
    assert "### Acer macrophyllum" in first_prompt
    assert "Family: Sapindaceae" in first_prompt
    assert "[accession:1968-0042]" in answer
