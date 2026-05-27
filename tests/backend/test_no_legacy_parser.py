"""AC-W1-A3: Hermes banner regex parser is removed.

The legacy `agent_bridge.py:_parse_hermes_output` and its regex
constants were the bridge between `hermes chat -q`'s terminal formatting
and the chat UI. With ACP as the universal transport (Fase 1+), the
parser is dead code. This test enforces its removal so it doesn't creep
back via a stray import or copy-paste.
"""

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent / "backend"

FORBIDDEN = (
    "_BANNER_OPEN_RE",
    "_BANNER_CLOSE_RE",
    "_parse_hermes_output",
)


def test_no_banner_parser_remnants_in_backend():
    offenders: list[str] = []
    for py in BACKEND.rglob("*.py"):
        source = py.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in source:
                offenders.append(f"{py.relative_to(BACKEND)}: {token}")
    assert not offenders, "Legacy banner parser remnants found:\n  " + "\n  ".join(offenders)
