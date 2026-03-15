"""Configuration — reads from root .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load root .env (two levels up from scripts/sim-agent/)
_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ROOT_ENV)


# LLM connection — reuses the platform's LiteLLM proxy
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
LLM_MODEL = os.getenv("OPENAI_MODEL", "")
LLM_NARRATOR_MODEL = os.getenv("LLM_QUICK_MODEL", os.getenv("OPENAI_MODEL", ""))

# MCP gateway connection
MCP_URL = os.getenv("SIM_AGENT_MCP_URL", "http://localhost:8020/mcp")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")
MCP_USER_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")

# Paths
SIM_AGENT_DIR = Path(__file__).resolve().parent
PERSONAS_DIR = SIM_AGENT_DIR / "personas"
SCENARIOS_DIR = SIM_AGENT_DIR / "scenarios"
RESULTS_DIR = SIM_AGENT_DIR / "results"


def validate(dry_run: bool = False) -> list[str]:
    """Return list of validation errors (empty = OK)."""
    errors = []

    if not LLM_API_KEY:
        errors.append("OPENAI_API_KEY is required")
    if not LLM_BASE_URL:
        errors.append("OPENAI_BASE_URL is required")
    if not LLM_MODEL:
        errors.append("OPENAI_MODEL is required")

    if not dry_run:
        if not MCP_API_KEY:
            errors.append("MCP_API_KEY is required")

    return errors
