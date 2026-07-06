from __future__ import annotations

from pathlib import Path

from ben0.assistant.model_adapters import MockModelAdapter
from ben0.assistant.orchestrator import AssistantOrchestrator
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.ingest.csv_ingest import ingest_all_csvs
from ben0.ingest.document_ingest import ingest_documents
from ben0.retrieval.index import build_index
from ben0.session import ConversationTurn
from ben0.synthetic.generate_dataset import generate_all
from ben0.validation.engine import run_validation


class CriticMockAdapter(MockModelAdapter):
    def generate(self, prompt: str, system: str | None = None) -> str:
        if system and "evidence auditor" in system.lower():
            return (
                "Assessment: partially_supported\n"
                "Issues:\n"
                "1. One summary claim could use a second citation.\n"
                "Suggestions:\n"
                "1. Add another citation if available."
            )
        return super().generate(prompt, system=system)


class CapturePromptAdapter:
    def __init__(self) -> None:
        self.prompt = ""
        self.system = ""

    @property
    def model_name(self) -> str:
        return "capture"

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.prompt = prompt
        self.system = system or ""
        return "FINAL: Captured prompt. [assistant:test]"


def _prepare_dataset(tmp_path: Path) -> str:
    synthetic_dir = tmp_path / "synthetic"
    db_url = f"sqlite:///{tmp_path / 'ben0-r5.db'}"

    reset_singletons()
    generate_all(synthetic_dir)
    init_db(db_url)
    ingest_all_csvs(synthetic_dir, db_url=db_url)
    ingest_documents(synthetic_dir / "documents", db_url=db_url)

    session = get_session(db_url)
    try:
        run_validation(session)
        build_index(session)
    finally:
        session.close()

    return db_url


def test_orchestrator_appends_verification_appendix(tmp_path: Path) -> None:
    db_url = _prepare_dataset(tmp_path)
    try:
        orchestrator = AssistantOrchestrator(
            adapter=MockModelAdapter(),
            session_factory=lambda: get_session(db_url),
        )

        answer = orchestrator.answer("How many accessions?")

        assert "[collection_summary:metrics]" in answer
        assert "Evidence Check:" in answer
        assert "confidence" in answer.lower()
    finally:
        reset_singletons()


def test_orchestrator_appends_critic_output_when_enabled(tmp_path: Path) -> None:
    db_url = _prepare_dataset(tmp_path)
    try:
        orchestrator = AssistantOrchestrator(
            adapter=CriticMockAdapter(),
            session_factory=lambda: get_session(db_url),
            enable_critic=True,
        )

        answer = orchestrator.answer("How many accessions?")

        assert "Evidence Check:" in answer
        assert "🧪 Critic:" in answer
        assert "partially supported" in answer
    finally:
        reset_singletons()


def test_orchestrator_injects_recent_conversation_block(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'ben0-history.db'}"
    reset_singletons()
    init_db(db_url)

    adapter = CapturePromptAdapter()
    orchestrator = AssistantOrchestrator(
        adapter=adapter,
        session_factory=lambda: get_session(db_url),
    )
    session = orchestrator.session_manager.create_session(name="history-test", model_adapter="capture")
    session.turns = [
        ConversationTurn(role="user", content="Tell me about Acer macrophyllum.", timestamp="2026-07-05T00:00:00"),
        ConversationTurn(role="assistant", content="It is represented in the collection.", timestamp="2026-07-05T00:00:01"),
        ConversationTurn(role="user", content="Which bed is it in?", timestamp="2026-07-05T00:00:02"),
        ConversationTurn(role="assistant", content="The records mention ALP1.", timestamp="2026-07-05T00:00:03"),
    ]
    orchestrator.current_session = session

    try:
        answer = orchestrator.answer("Tell me more about that.")

        assert "## Recent conversation" in adapter.prompt
        assert "User: Tell me about Acer macrophyllum." in adapter.prompt
        assert "Assistant: The records mention ALP1." in adapter.prompt
        assert "User: Tell me more about that." not in adapter.prompt
        assert "[assistant:test]" in answer
    finally:
        reset_singletons()
