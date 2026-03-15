"""YAML persona loader."""

from pathlib import Path

import yaml

from config import PERSONAS_DIR


def load_persona(name: str) -> dict:
    """Load a persona by name (filename without extension)."""
    path = PERSONAS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Persona not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def list_personas() -> list[str]:
    """Return available persona names."""
    return sorted(p.stem for p in PERSONAS_DIR.glob("*.yaml"))
