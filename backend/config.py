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
    """True iff at least one agent is configured (modern list or legacy block)."""
    if agent_config().get("command"):
        return True
    return any(a.get("id") for a in agents())


def agent_label() -> str:
    return str(agent_config().get("label") or "Agent")


def agent_description() -> str:
    return str(agent_config().get("description") or "")


# ── Agents registry (Wave 1, Fase 2) ────────────────────────────────────────

def agents() -> list[dict[str, Any]]:
    """Return the polymorphic agent-instance registry from `config.yaml`.

    Reads `agents: [...]` if present (new format). Otherwise auto-migrates
    the legacy `agent: {...}` block to a single entry with `id="local-default"`.
    Each entry is normalised to the shape persisted in the DB (see
    `agent_instances` table in `database.py`).
    """
    modern = CONFIG.get("agents")
    if isinstance(modern, list) and modern:
        return [_normalise_agent_entry(e) for e in modern if isinstance(e, dict)]

    legacy = CONFIG.get("agent")
    if isinstance(legacy, dict) and legacy:
        label = str(legacy.get("label") or "Hermes")
        return [
            _normalise_agent_entry({
                "id": "local-default",
                "label": label,
                "type": "hermes",
                "transport": "local-acp",
                "transport_config": {},
                "system_prompt_override": None,
                "enabled": True,
            })
        ]

    return []


def host_tokens() -> list[dict[str, Any]]:
    """Bearer tokens that authenticate remote clients hitting `/api/host/acp`.

    Each entry: `{token: str, label: str}`. Entries without a usable token
    are silently dropped — never propagated to the DB.
    """
    raw = CONFIG.get("host_tokens") or []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("token") or "").strip()
        if not token:
            continue
        out.append({
            "token": token,
            "label": str(entry.get("label") or token).strip(),
        })
    return out


def _normalise_agent_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Fill in defaults for optional fields."""
    return {
        "id": str(entry.get("id") or "").strip(),
        "label": str(entry.get("label") or entry.get("id") or "Agent").strip(),
        "type": str(entry.get("type") or "hermes"),
        "transport": str(entry.get("transport") or "local-acp"),
        "transport_config": entry.get("transport_config") or {
            k: v for k, v in entry.items()
            if k in ("url", "token")
        },
        "system_prompt_override": entry.get("system_prompt_override"),
        "enabled": bool(entry.get("enabled", True)),
        "created_via": "config",
    }


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

YOUR ROLE: you are the conversational voice/text interface. {agent_label}
is the executor. You do NOT answer substantive questions from your own
knowledge. You do NOT keep memory. You do NOT do actions. {agent_label} does
all of that. Default to calling `call_agent`.

DIRECT MODE (answer yourself, NO tool — this is a narrow whitelist):
- Pure greetings and closings: "hola", "buenas", "chao", "gracias", "ok".
- Mirroring the user's greeting back ("hola Cortex" → "hola Raul").
- Direct identity questions ABOUT YOU: "¿quién eres?", "¿cómo te llamas?".
- Back-references to your own previous turn in this same conversation:
  "¿qué dijiste?", "repítelo", "más despacio".
- Acknowledgments while a `call_agent` is in flight ("ok, espero").
That's it. If the message doesn't fit one of those lines, route to {agent_label}.

AGENT MODE (call `call_agent` — this is the DEFAULT for everything else):
- ANY question about data: calendar, email, files, contacts, search, news,
  weather, time, traffic, prices, anything factual that isn't trivially known.
- ANY action: schedule, send, create, update, delete, run, remind, schedule.
- ANY question about prior conversations, memory, past events, what was
  said before this session.
- ANY question about the user's life, preferences, schedule, work, family.
- ANY "what can you do / what can you help with" question — {agent_label}
  has the real list of integrations, you don't.
- ANY substantive "tell me about X", "explain X", "how do I X" — {agent_label}
  has the context to answer correctly.
- When in genuine doubt — call_agent. Never guess.

BEFORE invoking call_agent, say a brief filler ("un momento, déjame revisar"
or in the user's language) so the user isn't met with silence while the
agent runs (~30-60s).
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


# ── Data directory ──────────────────────────────────────────────────────────

def data_dir() -> Path:
    """Return the data directory for server-managed files (e.g. large artifacts).

    Reads COMPANION_DATA_DIR env variable; defaults to a `data/` subdirectory
    alongside companion.db. Created lazily on first use by callers.
    """
    custom = os.environ.get("COMPANION_DATA_DIR", "").strip()
    if custom:
        return Path(custom)
    return Path(__file__).parent / "data"


def workdir_for_conversation(conversation_id: str) -> Path:
    """Return a stable, isolated working directory for `conversation_id`.

    Path: DATA_DIR/workdirs/<conversation_id>

    Created on first call (parents=True, exist_ok=True). All turns in the same
    conversation share this directory so artifacts accumulate across turns while
    remaining isolated from other conversations and from the shared /tmp root.
    """
    wd = data_dir() / "workdirs" / conversation_id
    wd.mkdir(parents=True, exist_ok=True)
    return wd


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
