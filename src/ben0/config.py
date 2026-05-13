"""BEN-0 configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_HERE = Path(__file__).parent


def _find_root() -> Path:
    """Locate the project root using a safe resolution strategy.

    1. Honour the BEN0_ROOT environment variable if set.
    2. Walk up from cwd looking for a pyproject.toml that mentions ben0.
    3. Fall back to ~/.ben0/ as a user data directory.
    """
    # 1. Explicit env var
    env_root = os.environ.get("BEN0_ROOT")
    if env_root:
        return Path(env_root)

    # 2. Walk up from cwd looking for pyproject.toml with ben0
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        pyproject = parent / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text(encoding="utf-8")
                if "ben0" in text:
                    return parent
            except Exception:
                pass

    # 3. User data directory
    user_dir = Path.home() / ".ben0"
    user_dir.mkdir(exist_ok=True)
    return user_dir


def _find_garden_root() -> Path:
    """Find the active garden root, or fallback to legacy root.

    Returns the data root for the current active garden if one exists,
    otherwise falls back to the legacy single-directory behavior.
    """
    root = _find_root()
    active_file = root / "gardens" / ".active"

    if active_file.exists():
        try:
            garden_slug = active_file.read_text(encoding="utf-8").strip()
            if garden_slug:
                garden_root = root / "gardens" / garden_slug
                if garden_root.exists():
                    return garden_root
        except Exception:
            pass

    return root


def _make_garden_slug(garden_name: str) -> str:
    """Convert garden name to filesystem-safe slug."""
    return garden_name.lower().replace(" ", "-").replace("_", "-")


def get_active_garden() -> str | None:
    """Get the name of the currently active garden, if any."""
    root = _find_root()
    active_file = root / "gardens" / ".active"

    if active_file.exists():
        try:
            return active_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return None


def set_active_garden(garden_name: str) -> None:
    """Set the active garden by name."""
    root = _find_root()
    garden_slug = _make_garden_slug(garden_name)
    garden_dir = root / "gardens" / garden_slug

    if not garden_dir.exists():
        raise ValueError(f"Garden '{garden_name}' (slug: {garden_slug}) does not exist")

    active_file = root / "gardens" / ".active"
    active_file.parent.mkdir(exist_ok=True)
    active_file.write_text(garden_slug, encoding="utf-8")


def list_gardens() -> list[str]:
    """List all available gardens."""
    root = _find_root()
    gardens_dir = root / "gardens"

    if not gardens_dir.exists():
        return []

    gardens = []
    for item in gardens_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            gardens.append(item.name)
    return sorted(gardens)


def create_garden(garden_name: str) -> Path:
    """Create a new garden workspace and return its path."""
    root = _find_root()
    garden_slug = _make_garden_slug(garden_name)
    garden_root = root / "gardens" / garden_slug

    # Create garden directory structure
    for subdir in ("data", "data/synthetic", "data/raw", "data/processed",
                   "data/documents", "data/exports", "data/rules", "data/codex", "data/vector"):
        (garden_root / subdir).mkdir(parents=True, exist_ok=True)

    return garden_root


_ROOT = _find_root()
_GARDEN_ROOT = _find_garden_root()

# Ensure essential data subdirectories exist
for _subdir in ("data", "data/synthetic", "data/raw", "data/processed",
                "data/documents", "data/exports", "data/rules", "data/codex", "data/vector"):
    (_GARDEN_ROOT / _subdir).mkdir(parents=True, exist_ok=True)


def _path(env_key: str, default: str) -> Path:
    raw = os.environ.get(env_key, default)
    path = Path(raw)
    if not path.is_absolute():
        path = _GARDEN_ROOT / path
    return path


def reset_singletons() -> None:
    """Reset garden-aware paths when switching gardens.

    This function is called by the db.session module, but we also
    need to reset our garden root when the active garden changes.
    """
    global _GARDEN_ROOT
    _GARDEN_ROOT = _find_garden_root()

    for _subdir in ("data", "data/synthetic", "data/raw", "data/processed",
                    "data/documents", "data/exports", "data/rules", "data/codex", "data/vector"):
        (_GARDEN_ROOT / _subdir).mkdir(parents=True, exist_ok=True)

    # Import here to avoid circular dependency
    from ben0.db.session import reset_singletons as reset_db_singletons
    reset_db_singletons()


DB_URL: str = os.environ.get("BEN0_DB_URL", f"sqlite:///{_GARDEN_ROOT / 'data' / 'ben0.db'}")

DATA_DIR: Path = _path("BEN0_DATA_DIR", "data")
SYNTHETIC_DIR: Path = _path("BEN0_SYNTHETIC_DIR", "data/synthetic")
RAW_DIR: Path = _path("BEN0_RAW_DIR", "data/raw")
PROCESSED_DIR: Path = _path("BEN0_PROCESSED_DIR", "data/processed")
DOCUMENTS_DIR: Path = _path("BEN0_DOCUMENTS_DIR", "data/documents")
EXPORTS_DIR: Path = _path("BEN0_EXPORTS_DIR", "data/exports")

INSTITUTION_NAME: str = os.environ.get(
    "BEN0_INSTITUTION_NAME", "Cascadia Demonstration Botanical Garden"
)
INSTITUTION_CODE: str = os.environ.get("BEN0_INSTITUTION_CODE", "CDBG")

LOG_LEVEL: str = os.environ.get("BEN0_LOG_LEVEL", "INFO")

MODEL_ADAPTER: str = os.environ.get("BEN0_MODEL_ADAPTER", "mock")
MODEL_NAME: str = os.environ.get("BEN0_MODEL_NAME", "")
OLLAMA_URL: str = os.environ.get("BEN0_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("BEN0_OLLAMA_MODEL", "gemma3:12b")

ALLOW_PUBLIC_EXPORT: bool = os.environ.get("BEN0_ALLOW_PUBLIC_EXPORT", "false").lower() == "true"
