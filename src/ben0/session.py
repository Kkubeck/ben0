"""Session management for BEN-0 conversations."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ben0 import config


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: str


@dataclass
class Session:
    """A complete conversation session."""
    session_id: str
    name: str
    created_at: str
    updated_at: str
    model_adapter: str
    garden: str | None
    turns: list[ConversationTurn]


class SessionManager:
    """Manages session storage and retrieval."""

    def __init__(self):
        # Sessions are stored in the garden root or data root if no garden
        garden_root = config._find_garden_root()
        self.sessions_dir = garden_root / "sessions"
        self.sessions_dir.mkdir(exist_ok=True)

    def create_session(self, name: str | None = None, model_adapter: str = "mock") -> Session:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        if not name:
            # Generate name from timestamp
            date_str = datetime.now().strftime("%Y-%m-%d")
            existing_today = len([f for f in self.sessions_dir.glob(f"session-{date_str}-*.json")])
            name = f"session-{date_str}-{existing_today + 1}"

        garden = config.get_active_garden()

        return Session(
            session_id=session_id,
            name=name,
            created_at=now,
            updated_at=now,
            model_adapter=model_adapter,
            garden=garden,
            turns=[]
        )

    def save_session(self, session: Session) -> None:
        """Save session to disk."""
        session.updated_at = datetime.now().isoformat()

        session_file = self.sessions_dir / f"{session.name}.json"
        session_data = asdict(session)

        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

    def load_session(self, session_id_or_name: str) -> Session | None:
        """Load session from disk by ID or name."""
        # Try by name first
        session_file = self.sessions_dir / f"{session_id_or_name}.json"
        if not session_file.exists():
            # Try to find by ID
            for file_path in self.sessions_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if data.get("session_id") == session_id_or_name:
                            session_file = file_path
                            break
                except (json.JSONDecodeError, OSError):
                    continue
            else:
                return None

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Convert turn dictionaries back to ConversationTurn objects
            turns = [ConversationTurn(**turn) for turn in data.get("turns", [])]

            return Session(
                session_id=data["session_id"],
                name=data["name"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                model_adapter=data["model_adapter"],
                garden=data.get("garden"),
                turns=turns
            )
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions with metadata."""
        sessions = []

        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                sessions.append({
                    "name": data["name"],
                    "session_id": data["session_id"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "model_adapter": data["model_adapter"],
                    "garden": data.get("garden"),
                    "turn_count": len(data.get("turns", []))
                })
            except (json.JSONDecodeError, OSError, KeyError):
                continue

        # Sort by updated_at descending (most recent first)
        sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        return sessions

    def delete_session(self, session_name: str) -> bool:
        """Delete a saved session by name."""
        session_file = self.sessions_dir / f"{session_name}.json"
        if session_file.exists():
            session_file.unlink()
            return True
        return False

    def add_turn(self, session: Session, role: str, content: str) -> None:
        """Add a conversation turn to the session."""
        timestamp = datetime.now().isoformat()
        turn = ConversationTurn(role=role, content=content, timestamp=timestamp)
        session.turns.append(turn)

    def auto_name_from_first_question(self, session: Session) -> str:
        """Generate a session name from the first user question."""
        if not session.turns:
            return session.name

        first_user_turn = next((turn for turn in session.turns if turn.role == "user"), None)
        if not first_user_turn:
            return session.name

        # Take first few words, clean them up
        words = first_user_turn.content.split()[:4]
        clean_words = []
        for word in words:
            # Remove punctuation and convert to lowercase
            clean_word = ''.join(c for c in word if c.isalnum()).lower()
            if clean_word:
                clean_words.append(clean_word)

        if clean_words:
            name = "-".join(clean_words)
            # Ensure unique name
            base_name = name
            counter = 1
            while (self.sessions_dir / f"{name}.json").exists():
                name = f"{base_name}-{counter}"
                counter += 1
            return name

        return session.name