"""
Configuration loader for hermes-companion.

Reads `config.yaml` from the repo root (one directory above `backend/`). If
that file doesn't exist, falls back to `config.yaml.example` and prints a
notice so first-time users get a working default without manual setup.

The loaded config is exposed as module-level `CONFIG` plus a few helpers that
build the system prompt and seed the user table.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
EXAMPLE_PATH = REPO_ROOT / "config.yaml.example"


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return _load_yaml(CONFIG_PATH)
    if EXAMPLE_PATH.exists():
        print(
            f"[config] {CONFIG_PATH.name} not found — using {EXAMPLE_PATH.name} defaults. "
            "Copy it to config.yaml and edit to customize."
        )
        return _load_yaml(EXAMPLE_PATH)
    raise FileNotFoundError(
        f"No config found. Expected {CONFIG_PATH} or {EXAMPLE_PATH}."
    )


CONFIG: dict[str, Any] = _load_config()


# ── Public accessors ────────────────────────────────────────────────────────

def assistant_name() -> str:
    return str(CONFIG.get("assistant_name") or "Companion")


def company_name() -> str:
    return str(CONFIG.get("company_name") or "Your Company")


def company_url() -> str:
    return str(CONFIG.get("company_url") or "")


def default_language() -> str:
    return str(CONFIG.get("default_language") or "en")


_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
}


def language_name() -> str:
    code = default_language().lower()
    return _LANGUAGE_NAMES.get(code, code)


def personality() -> str:
    return str(CONFIG.get("personality") or "Warm, professional, helpful.")


def agent_config() -> dict[str, Any]:
    return dict(CONFIG.get("agent") or {})


def agent_enabled() -> bool:
    return bool(agent_config().get("command"))


def agent_label() -> str:
    return str(agent_config().get("label") or "Agent")


def agent_command() -> list[str]:
    cmd = agent_config().get("command") or []
    return [str(x) for x in cmd]


def agent_timeout() -> float:
    return float(agent_config().get("timeout_seconds") or 180)


def agent_description() -> str:
    return str(agent_config().get("description") or "")


def team() -> list[dict[str, Any]]:
    raw = CONFIG.get("team") or []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        uid = str(entry.get("id") or "").strip()
        name = str(entry.get("name") or uid).strip()
        if not uid or not name:
            continue
        out.append({
            "id": uid,
            "name": name,
            "role": str(entry.get("role") or ""),
            "shared_space": bool(entry.get("shared_space", False)),
        })
    return out


# ── System prompt builder ───────────────────────────────────────────────────

_DEFAULT_PROMPT_TEMPLATE = """You are {assistant_name}, the voice assistant for {company_name}{company_url_block}.

Your team:
{team_block}

Personality: {personality}

═══ VOICE RULES ═══
- Keep replies short (2-3 sentences max) and conversational, like a phone call.
- No markdown, no bullet lists, no emojis, no long URLs.
- If the user shares an image (vision mode), do NOT describe what you see
  unless they explicitly ask. Use the image as silent context — for greetings
  and answers that don't ask "what do you see?", behave as if you only had audio.

═══ ROUTING ═══
{routing_block}
"""

_ROUTING_WITH_AGENT = """You have ONE tool: `call_agent`. It runs {agent_label} — {agent_description}

DIRECT MODE (answer yourself, no tool):
- Greetings, chitchat, identity questions ("who are you?", "what can you do?").
- General knowledge (capitals, definitions, simple math).
- Clarifications about something you just said in this conversation.

AGENT MODE (call `call_agent`):
- Anything requiring live data (calendar, email, files, web search).
- Anything requiring action (scheduling, sending messages, running automations).
- Memory of past conversations.
- If in doubt, prefer call_agent.

BEFORE invoking call_agent, say a brief filler ("one moment, let me check") so
the user isn't met with silence while the agent runs (~30-60s).
"""

_ROUTING_NO_AGENT = """You do NOT have any tools available. Answer everything directly
using your own knowledge. If asked about live data (calendar, email, files,
current events) say you can't access that and offer the best response you can
from general knowledge.
"""


def _team_block() -> str:
    members = team()
    if not members:
        return "(no team configured — set `team:` in config.yaml)"
    lines = []
    for m in members:
        if m["shared_space"]:
            lines.append(f"- {m['name']} (shared space — group conversations)")
        elif m["role"]:
            lines.append(f"- {m['name']}: {m['role']}")
        else:
            lines.append(f"- {m['name']}")
    return "\n".join(lines)


def _routing_block() -> str:
    if agent_enabled():
        return _ROUTING_WITH_AGENT.format(
            agent_label=agent_label(),
            agent_description=agent_description() or "an external agent backend",
        )
    return _ROUTING_NO_AGENT


def system_prompt_core() -> str:
    """Return the system prompt sans per-session user context.

    If the config sets `system_prompt:` directly, that wins. Otherwise we
    render the default template with the configured identity/team/personality.
    """
    explicit = CONFIG.get("system_prompt")
    if explicit and isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    url = company_url().strip()
    url_block = f" ({url})" if url else ""
    return _DEFAULT_PROMPT_TEMPLATE.format(
        assistant_name=assistant_name(),
        company_name=company_name(),
        company_url_block=url_block,
        team_block=_team_block(),
        personality=personality(),
        routing_block=_routing_block(),
    )


# ── Env helpers ─────────────────────────────────────────────────────────────

def load_dotenv_if_present() -> None:
    """Load `.env` from the repo root into os.environ. No-op if missing.

    Kept dependency-free — same format as a typical dotenv file (KEY=VALUE,
    `#` comments, blank lines). Existing env vars take precedence.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
