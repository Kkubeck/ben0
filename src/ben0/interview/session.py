"""Persistent state management for institution interviews."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ben0.interview.questions import DEFAULT_QUESTIONS, InterviewQuestion


@dataclass
class InterviewState:
    garden_name: str
    started_at: str
    completed_questions: list[str] = field(default_factory=list)
    skipped_questions: list[str] = field(default_factory=list)
    current_question: str | None = None
    answers: dict[str, str] = field(default_factory=dict)


class InterviewSession:
    def __init__(self, state_path: Path, questions: list[InterviewQuestion] | None = None):
        self.state_path = state_path
        self.questions = questions or list(DEFAULT_QUESTIONS)
        self._question_ids = [question.question_id for question in self.questions]

    def load_or_create(self, garden_name: str) -> InterviewState:
        """Load existing interview state or create new."""
        if self.state_path.exists():
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                return InterviewState(
                    garden_name=str(payload.get("garden_name") or garden_name),
                    started_at=str(payload.get("started_at") or _now_iso()),
                    completed_questions=list(payload.get("completed_questions") or []),
                    skipped_questions=list(payload.get("skipped_questions") or []),
                    current_question=payload.get("current_question"),
                    answers=dict(payload.get("answers") or {}),
                )
            except Exception:
                pass

        state = InterviewState(garden_name=garden_name, started_at=_now_iso())
        self.save(state)
        return state

    def save(self, state: InterviewState) -> None:
        """Save interview state to JSON file."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")

    def next_question(self, state: InterviewState) -> InterviewQuestion | None:
        """Get the next unanswered, unskipped question. Returns None if all done."""
        completed = set(state.completed_questions)
        skipped = set(state.skipped_questions)
        for question in self.questions:
            if question.question_id in completed or question.question_id in skipped:
                continue
            state.current_question = question.question_id
            return question
        state.current_question = None
        return None

    def mark_completed(self, state: InterviewState, question_id: str, answer: str) -> None:
        """Mark a question as completed with the given answer."""
        if question_id not in state.completed_questions:
            state.completed_questions.append(question_id)
        if question_id in state.skipped_questions:
            state.skipped_questions.remove(question_id)
        state.answers[question_id] = answer
        state.current_question = None

    def mark_skipped(self, state: InterviewState, question_id: str) -> None:
        """Mark a question as skipped."""
        if question_id not in state.skipped_questions:
            state.skipped_questions.append(question_id)
        if question_id in state.completed_questions:
            state.completed_questions.remove(question_id)
        state.answers.pop(question_id, None)
        state.current_question = None

    def is_complete(self, state: InterviewState) -> bool:
        """Check if all questions have been answered or skipped."""
        handled = set(state.completed_questions) | set(state.skipped_questions)
        return all(question_id in handled for question_id in self._question_ids)

    def reset(self, state: InterviewState) -> None:
        """Reset the interview (clear all answers, start over)."""
        state.completed_questions.clear()
        state.skipped_questions.clear()
        state.answers.clear()
        state.current_question = None
        state.started_at = _now_iso()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
