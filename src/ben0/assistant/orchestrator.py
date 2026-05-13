"""CLI orchestrator for the BEN-0 visiting scholar assistant."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from ben0 import config
from ben0.assistant.critic import critique_answer
from ben0.assistant.evidence_check import (
    VerificationResult,
    check_rule_compliance,
    detect_conflicts,
    score_confidence,
    verify_citations,
)
from ben0.assistant.model_adapters import MockModelAdapter, OllamaAdapter, OpenAICompatibleAdapter
from ben0.assistant.persona import VISITING_SCHOLAR_SYSTEM_PROMPT
from ben0.assistant.prompts import build_initial_prompt, build_tool_result_prompt
from ben0.assistant.tools import build_tool_registry
from ben0.db.session import get_session
from ben0.rules.inject import format_rules_for_prompt
from ben0.rules.loader import load_rules
from ben0.rules.matcher import match_rules
from ben0.rules.schema import RuleFile
from ben0.session import Session, SessionManager


@dataclass(slots=True)
class ParsedResponse:
    kind: str
    content: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None


class AssistantOrchestrator:
    def __init__(
        self,
        adapter: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        *,
        enable_critic: bool = False,
    ):
        self.adapter = adapter or _build_default_adapter()
        self.session_factory = session_factory or get_session
        self.session_manager = SessionManager()
        self.current_session: Session | None = None
        self.enable_critic = enable_critic
        self._last_retrieved_chunks: list[dict[str, Any]] = []
        self._last_matched_rules: list[RuleFile] = []

    def answer(self, question: str) -> str:
        self._last_retrieved_chunks = []
        self._last_matched_rules = []

        if self.current_session:
            self.session_manager.add_turn(self.current_session, "user", question)

        session = self.session_factory()
        try:
            registry = build_tool_registry(session)
            rules_dir = config._GARDEN_ROOT / "data" / "rules"
            self._last_matched_rules = match_rules(question, load_rules(rules_dir))
            system_prompt = VISITING_SCHOLAR_SYSTEM_PROMPT
            if self._last_matched_rules:
                system_prompt = f"{format_rules_for_prompt(self._last_matched_rules)}\n\n{system_prompt}"
            prompt = build_initial_prompt(question, sorted(registry))
            last_result: dict[str, Any] | None = None

            for _ in range(4):
                model_output = self.adapter.generate(prompt, system=system_prompt)
                parsed = self._parse_response(model_output)

                if parsed.kind == "tool" and parsed.tool_name:
                    tool = registry.get(parsed.tool_name)
                    if tool is None:
                        return self._record_and_return(
                            f"I do not have a tool named {parsed.tool_name}. [assistant:tool-error]"
                        )
                    arguments = parsed.arguments or {}
                    last_result = tool(**arguments)
                    self._capture_retrieved_chunks(last_result)
                    prompt = build_tool_result_prompt(question, parsed.tool_name, arguments, last_result)
                    continue

                if parsed.kind == "final" and parsed.content:
                    answer = self._ensure_citations(parsed.content, last_result)
                    return self._record_and_return(self._append_verification(answer))

            answer = self._fallback_answer(question, last_result)
            return self._record_and_return(self._append_verification(answer))
        finally:
            session.close()

    def chat(self, session_name: str | None = None) -> None:
        # Load or create session
        if session_name:
            loaded_session = self.session_manager.load_session(session_name)
            if loaded_session:
                self.current_session = loaded_session
                print(f"Resumed session '{session_name}'")
                self._show_recent_history(3)  # Show last 3 turns for context
            else:
                # Create new named session
                adapter_name = getattr(self.adapter, 'model_name', 'mock')
                self.current_session = self.session_manager.create_session(
                    name=session_name, model_adapter=adapter_name
                )
                print(f"Started new session '{session_name}'")
        else:
            # Create temporary session
            adapter_name = getattr(self.adapter, 'model_name', 'mock')
            self.current_session = self.session_manager.create_session(
                model_adapter=adapter_name
            )

        # Show the active model when starting chat
        model_display = getattr(self.adapter, 'model_name', 'unknown')
        if isinstance(self.adapter, OllamaAdapter):
            model_display = f"{model_display} via ollama"
        print(f"BEN-0 chat (model: {model_display}) — type exit or Ctrl+D to quit")
        print("Special commands: /save [name], /sessions, /load <name>, /history")

        while True:
            try:
                question = input("ben0> ").strip()
            except EOFError:
                print()
                break
            if not question:
                continue
            if question.lower() in {"exit", "quit", ":q"}:
                break

            # Handle special commands
            if question.startswith("/"):
                if self._handle_chat_command(question):
                    continue
                else:
                    break

            print(self.answer(question))

        # Auto-save on exit
        self._auto_save_on_exit()

    def _handle_chat_command(self, command: str) -> bool:
        """Handle special chat commands. Returns True to continue chat, False to exit."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd == "/save":
            name = parts[1] if len(parts) > 1 else None
            self.save_session(name)
            return True

        elif cmd == "/sessions":
            self._list_sessions_in_chat()
            return True

        elif cmd == "/load":
            if len(parts) < 2:
                print("Usage: /load <session_name>")
                return True
            session_name = parts[1]
            if self.load_session(session_name):
                self._show_recent_history(3)
            return True

        elif cmd == "/history":
            self._show_history()
            return True

        else:
            print(f"Unknown command: {cmd}")
            print("Available commands: /save [name], /sessions, /load <name>, /history")
            return True

    def _auto_save_on_exit(self) -> None:
        """Auto-save session on chat exit."""
        if not self.current_session or not self.current_session.turns:
            return

        # If session has a generated name and conversation exists, try to give it a better name
        if (self.current_session.name.startswith("session-") and
            len(self.current_session.name.split('-')) == 4):  # Default timestamp format
            better_name = self.session_manager.auto_name_from_first_question(self.current_session)
            if better_name != self.current_session.name:
                # Rename the session
                old_file = self.session_manager.sessions_dir / f"{self.current_session.name}.json"
                self.current_session.name = better_name
                if old_file.exists():
                    old_file.unlink()

        self.session_manager.save_session(self.current_session)
        print(f"Session auto-saved as '{self.current_session.name}'")

    def save_session(self, name: str | None = None) -> bool:
        """Save the current session."""
        if not self.current_session:
            print("No active session to save")
            return False

        if name and name != self.current_session.name:
            # Check if new name already exists
            if self.session_manager.load_session(name):
                print(f"Session '{name}' already exists")
                return False
            # Remove old session file if renaming
            old_file = self.session_manager.sessions_dir / f"{self.current_session.name}.json"
            self.current_session.name = name
            if old_file.exists():
                old_file.unlink()

        self.session_manager.save_session(self.current_session)
        print(f"Session saved as '{self.current_session.name}'")
        return True

    def load_session(self, session_id_or_name: str) -> bool:
        """Load a session by ID or name."""
        loaded_session = self.session_manager.load_session(session_id_or_name)
        if loaded_session:
            self.current_session = loaded_session
            print(f"Loaded session '{loaded_session.name}'")
            return True
        else:
            print(f"Session '{session_id_or_name}' not found")
            return False

    def _show_recent_history(self, max_turns: int = 5) -> None:
        """Show recent conversation history."""
        if not self.current_session or not self.current_session.turns:
            return

        recent_turns = self.current_session.turns[-max_turns * 2:]  # Get user+assistant pairs
        if not recent_turns:
            return

        print("\n--- Recent conversation ---")
        for turn in recent_turns:
            prefix = "ben0>" if turn.role == "user" else ""
            print(f"{prefix} {turn.content}")
        print("--- End history ---\n")

    def _show_history(self) -> None:
        """Show full conversation history."""
        if not self.current_session or not self.current_session.turns:
            print("No conversation history in current session")
            return

        print(f"\n--- Session '{self.current_session.name}' history ---")
        for turn in self.current_session.turns:
            prefix = "ben0>" if turn.role == "user" else ""
            print(f"{prefix} {turn.content}")
        print("--- End history ---\n")

    def _list_sessions_in_chat(self) -> None:
        """List sessions within chat interface."""
        sessions = self.session_manager.list_sessions()
        if not sessions:
            print("No saved sessions")
            return

        print("\nSaved sessions:")
        for session in sessions:
            garden_info = f" (garden: {session['garden']})" if session['garden'] else ""
            print(f"  {session['name']} - {session['turn_count']} turns, {session['model_adapter']}{garden_info}")
        print()

    def _parse_response(self, response: str) -> ParsedResponse:
        tool_match = re.search(r"TOOL_CALL\s+(\w+)\s+(\{.*\})", response, re.DOTALL)
        if tool_match:
            tool_name = tool_match.group(1)
            try:
                arguments = json.loads(tool_match.group(2))
            except json.JSONDecodeError:
                arguments = {}
            return ParsedResponse(kind="tool", tool_name=tool_name, arguments=arguments)

        final_match = re.search(r"FINAL:\s*(.*)", response, re.DOTALL)
        if final_match:
            return ParsedResponse(kind="final", content=final_match.group(1).strip())
        return ParsedResponse(kind="final", content=response.strip())

    def _ensure_citations(self, answer: str, result: dict[str, Any] | None) -> str:
        if "[" in answer and "]" in answer:
            return answer
        citations = self._collect_citations(result)
        if not citations:
            return f"{answer} [assistant:no-citation]"
        return f"{answer} {' '.join(citations[:5])}"

    def _collect_citations(self, result: Any) -> list[str]:
        citations: list[str] = []
        if isinstance(result, dict):
            for key, value in result.items():
                if key == "citation" and isinstance(value, str):
                    citations.append(f"[{value}]")
                else:
                    citations.extend(self._collect_citations(value))
        elif isinstance(result, list):
            for item in result:
                citations.extend(self._collect_citations(item))
        return list(dict.fromkeys(citations))

    def _capture_retrieved_chunks(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        extracted = self._extract_retrieved_chunks(result)
        if not extracted:
            return
        existing = {json.dumps(chunk, sort_keys=True, default=str) for chunk in self._last_retrieved_chunks}
        for chunk in extracted:
            marker = json.dumps(chunk, sort_keys=True, default=str)
            if marker in existing:
                continue
            self._last_retrieved_chunks.append(chunk)
            existing.add(marker)

    def _extract_retrieved_chunks(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        extracted: list[dict[str, Any]] = []
        for key in ("results", "accessions", "items", "taxa"):
            rows = result.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                extracted.append(
                    {
                        "chunk_id": row.get("chunk_id") or row.get("citation") or row.get("id"),
                        "citation": row.get("citation"),
                        "document_name": row.get("document_name"),
                        "source_type": row.get("source_type") or result.get("tool"),
                        "snippet": row.get("snippet") or row.get("text"),
                        "text": row.get("text") or self._row_text(key, row),
                        "accession_id": row.get("accession_id") or row.get("id") if key == "accessions" else row.get("accession_id"),
                        "item_id": row.get("item_id") or row.get("id") if key == "items" else row.get("item_id"),
                        "taxon_id": row.get("taxon_id") or row.get("id") if key == "taxa" else row.get("taxon_id"),
                        "score": row.get("score"),
                        "document_type": row.get("document_type"),
                        "reliability_tier": row.get("reliability_tier") or ("official" if key in {"accessions", "items", "taxa"} else None),
                        "source_file_path": row.get("source_file_path"),
                        "date": row.get("date") or row.get("event_date") or row.get("accession_date"),
                        "lane": row.get("lane"),
                    }
                )
        return extracted

    def _row_text(self, key: str, row: dict[str, Any]) -> str:
        if key == "accessions":
            return (
                f"Accession {row.get('accession_number')} taxon {row.get('taxon')} "
                f"year {row.get('accession_year')}"
            )
        if key == "items":
            return (
                f"Item {row.get('item_label')} status {row.get('life_status')} "
                f"accession {row.get('accession_number')}"
            )
        if key == "taxa":
            return f"Taxon {row.get('scientific_name')} family {row.get('family')}"
        return json.dumps(row, ensure_ascii=False, default=str)

    def _append_verification(self, answer: str) -> str:
        retrieved = list(self._last_retrieved_chunks)
        citation_report = verify_citations(answer, retrieved)
        lane_a = [chunk for chunk in retrieved if chunk.get("lane") == "A"]
        lane_b = [chunk for chunk in retrieved if chunk.get("lane") == "B"]
        conflicts = detect_conflicts(lane_a, lane_b)
        rule_violations = check_rule_compliance(answer, self._last_matched_rules)
        confidence = score_confidence(citation_report, rule_violations, conflicts, retrieved)
        verification = VerificationResult(citation_report, conflicts, rule_violations, confidence)

        appendix = verification.format_appendix()
        critique_note = ""
        if self.enable_critic:
            critique = critique_answer(
                self.adapter,
                answer,
                [str(chunk.get("text") or chunk.get("snippet") or "") for chunk in retrieved if chunk.get("text") or chunk.get("snippet")],
                self._last_matched_rules,
            )
            if critique.assessment != "supported" or critique.issues:
                issue_text = critique.issues[0] if critique.issues else critique.assessment.replace("_", " ")
                critique_note = f"🧪 Critic: {critique.assessment.replace('_', ' ')} — {issue_text}"

        if critique_note:
            appendix = f"{appendix}\n{critique_note}" if appendix else critique_note
        if appendix:
            return f"{answer}\n\n{appendix}"
        return answer

    def _record_and_return(self, answer: str) -> str:
        if self.current_session:
            self.session_manager.add_turn(self.current_session, "assistant", answer)
        return answer

    def _fallback_answer(self, question: str, result: dict[str, Any] | None) -> str:
        if not result:
            return "I could not gather enough evidence to answer that question. [assistant:no-result]"

        tool = result.get("tool")
        if tool == "search_records":
            accessions = result.get("accessions", [])
            if accessions:
                labels = ", ".join(
                    f"{row['accession_number']} [{row['citation']}]" for row in accessions[:10]
                )
                return f"For '{question}', I found these matching accessions: {labels}."
            return f"I did not find matching accessions for '{question}'. [search_records:none]"
        if tool == "list_validation_issues":
            issues = result.get("issues", [])
            if issues:
                labels = ", ".join(
                    f"{row['entity_label'] or row['entity_id']} [{row['citation']}]" for row in issues[:10]
                )
                return f"The matching validation issues are attached to: {labels}."
        if tool == "summarize_collection":
            summary = result.get("summary", {})
            return (
                "The collection summary currently shows "
                f"{summary.get('total_accessions', 0)} accessions, {summary.get('total_items', 0)} items, "
                f"and {summary.get('total_taxa', 0)} taxa [collection_summary:metrics]."
            )
        return self._ensure_citations(
            "I gathered evidence, but I could not turn it into a confident narrative answer.",
            result,
        )


def _build_default_adapter() -> Any:
    adapter_name = (config.MODEL_ADAPTER or "mock").strip().lower()
    if adapter_name == "ollama":
        return OllamaAdapter()
    if adapter_name in {"openai", "openai-compatible", "openai_compatible"}:
        return OpenAICompatibleAdapter()
    return MockModelAdapter()
