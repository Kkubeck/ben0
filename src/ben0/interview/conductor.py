"""Interactive interview loop for institution-specific rule gathering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import click
from sqlalchemy.orm import Session

from ben0.interview.answer_parser import parse_answer_to_rule
from ben0.interview.data_gather import gather_db_context
from ben0.interview.questions import DEFAULT_QUESTIONS, InterviewQuestion
from ben0.interview.session import InterviewSession
from ben0.retrieval.search import search_index


@dataclass(slots=True)
class InterviewSummary:
    questions_answered: int
    questions_skipped: int
    rules_generated: int
    rule_files: list[str]


class InterviewConductor:
    """Runs the interactive institution interview."""

    def __init__(
        self,
        adapter: Any,
        session_factory: Callable[[], Session],
        rules_dir: Path,
        state_path: Path,
        garden_name: str,
    ):
        self.adapter = adapter
        self.session_factory = session_factory
        self.rules_dir = rules_dir
        self.state_path = state_path
        self.garden_name = garden_name
        self.questions = list(DEFAULT_QUESTIONS)
        self.state_manager = InterviewSession(state_path, self.questions)

    def run(self) -> InterviewSummary:
        """Run the full interactive interview. Returns summary when done."""
        click.echo(
            "Welcome to the BEN-0 Institution Interview! I'm going to ask you some questions about how your garden "
            "manages its collection. This helps me understand your data correctly. You can type 'skip' to skip any "
            "question, or 'quit' to save and exit (you can resume later)."
        )

        state = self.state_manager.load_or_create(self.garden_name)
        if state.completed_questions or state.skipped_questions:
            click.echo(
                f"Resuming interview for {state.garden_name}. "
                f"Answered {len(state.completed_questions)}/{len(self.questions)}, skipped {len(state.skipped_questions)}."
            )

        self.rules_dir.mkdir(parents=True, exist_ok=True)

        try:
            while True:
                question = self.state_manager.next_question(state)
                self.state_manager.save(state)
                if question is None:
                    break

                context = self._gather_context(question)
                prompt = self._format_question(question, context)
                click.echo()
                click.echo(f"[{question.title}]")
                click.echo(prompt)

                while True:
                    try:
                        raw_answer = input("you> ").strip()
                    except EOFError:
                        click.echo("\nSaved interview state. You can resume later with 'ben0 interview'.")
                        self.state_manager.save(state)
                        return self._build_summary(state)
                    except KeyboardInterrupt:
                        click.echo("\nSaved interview state after interrupt. You can resume later with 'ben0 interview'.")
                        self.state_manager.save(state)
                        return self._build_summary(state)

                    command = raw_answer.lower()
                    if command in {"quit", "exit"}:
                        click.echo("Saved interview state. You can resume later with 'ben0 interview'.")
                        self.state_manager.save(state)
                        return self._build_summary(state)
                    if command == "status":
                        self._show_status(state)
                        continue
                    if command == "back":
                        if self._step_back(state, question.question_id):
                            self.state_manager.save(state)
                            click.echo("Going back to the previous question.")
                            break
                        click.echo("No previous answered or skipped question to go back to.")
                        continue
                    if command == "skip":
                        self.state_manager.mark_skipped(state, question.question_id)
                        self.state_manager.save(state)
                        click.echo("Skipped. Moving on...")
                        break
                    if not raw_answer:
                        click.echo("Please answer, or type 'skip', 'status', 'back', or 'quit'.")
                        continue

                    answer = raw_answer
                    if self._answer_is_vague(answer) and question.followup_prompt:
                        click.echo(question.followup_prompt)
                        try:
                            followup = input("you> ").strip()
                        except (EOFError, KeyboardInterrupt):
                            followup = ""

                        followup_command = followup.lower()
                        if followup_command in {"quit", "exit"}:
                            click.echo("Saved interview state. You can resume later with 'ben0 interview'.")
                            self.state_manager.save(state)
                            return self._build_summary(state)
                        if followup_command == "skip":
                            self.state_manager.mark_skipped(state, question.question_id)
                            self.state_manager.save(state)
                            click.echo("Skipped. Moving on...")
                            break
                        if followup:
                            answer = f"{answer}\n\nFollow-up detail:\n{followup}"

                    rule = parse_answer_to_rule(question, answer, self.adapter, context=context)
                    rule_path = self.rules_dir / f"{rule.id}.yaml"
                    rule.source_path = rule_path
                    rule_path.write_text(rule.to_yaml(), encoding="utf-8")
                    self.state_manager.mark_completed(state, question.question_id, answer)
                    self.state_manager.save(state)
                    click.echo("Got it! I've saved that as a rule. Moving on...")
                    break

        finally:
            self.state_manager.save(state)

        summary = self._build_summary(state)
        click.echo()
        click.echo(
            f"Interview complete! Generated {summary.rules_generated} rules from "
            f"{summary.questions_answered} answers ({summary.questions_skipped} skipped)."
        )
        return summary

    def _gather_context(self, question: InterviewQuestion) -> str | None:
        parts: list[str] = []
        session = self.session_factory()
        try:
            if question.db_query:
                parts.append(gather_db_context(session, question.db_query))
            if question.data_query:
                parts.append(self._gather_search_context(session, question.data_query))
        finally:
            session.close()

        joined = " ".join(part.strip() for part in parts if part and part.strip())
        return joined or None

    def _gather_search_context(self, session: Session, query: str) -> str:
        try:
            results = search_index(session, query, limit=5, lane="A")
        except Exception:
            return "No indexed evidence found for this topic yet."

        if not results:
            return "No indexed evidence found for this topic yet."

        snippets = []
        for result in results:
            document = result.get("document_name") or "unknown document"
            snippet = str(result.get("snippet") or result.get("text") or "").strip()
            if snippet:
                snippets.append(f"{document}: {snippet}")
        if not snippets:
            return "No indexed evidence found for this topic yet."
        return "Lane A notes: " + " | ".join(snippets)

    def _format_question(self, question: InterviewQuestion, context: str | None) -> str:
        if question.db_query or question.data_query:
            return question.prompt_template.format(context=context or "No data found for this category yet.")
        return question.prompt_template

    def _show_status(self, state) -> None:
        total = len(self.questions)
        answered = len(state.completed_questions)
        skipped = len(state.skipped_questions)
        remaining = total - answered - skipped
        click.echo(
            f"Progress: {answered}/{total} answered, {skipped} skipped, {remaining} remaining."
        )

    def _step_back(self, state, current_question_id: str) -> bool:
        current_index = self._question_index(current_question_id)
        for question in reversed(self.questions[:current_index]):
            question_id = question.question_id
            if question_id in state.completed_questions:
                state.completed_questions.remove(question_id)
                state.answers.pop(question_id, None)
                state.current_question = question_id
                return True
            if question_id in state.skipped_questions:
                state.skipped_questions.remove(question_id)
                state.current_question = question_id
                return True
        return False

    def _question_index(self, question_id: str) -> int:
        for idx, question in enumerate(self.questions):
            if question.question_id == question_id:
                return idx
        return 0

    def _answer_is_vague(self, answer: str) -> bool:
        return len(answer.split()) < 8

    def _build_summary(self, state) -> InterviewSummary:
        rule_files: list[str] = []
        for question in self.questions:
            if question.question_id not in state.completed_questions:
                continue
            rule_path = self.rules_dir / f"{question.rule_id}.yaml"
            if rule_path.exists():
                rule_files.append(str(rule_path))
        return InterviewSummary(
            questions_answered=len(state.completed_questions),
            questions_skipped=len(state.skipped_questions),
            rules_generated=len(rule_files),
            rule_files=rule_files,
        )
