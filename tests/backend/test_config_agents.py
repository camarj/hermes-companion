"""AC-W1-D2 (config side): `config.agents()` reads new + legacy formats.

Tests are pure — they monkeypatch the loaded `CONFIG` dict; no I/O.
"""

import config


def test_agents_returns_modern_list_as_is(monkeypatch):
    monkeypatch.setattr(config, "CONFIG", {
        "agents": [
            {
                "id": "vps-prod",
                "label": "Hermes VPS prod",
                "transport": "remote-acp",
                "url": "wss://vps.example.com/api/host/acp",
                "token": "env:HERMES_VPS_TOKEN",
            },
        ],
    })

    out = config.agents()

    assert len(out) == 1
    assert out[0]["id"] == "vps-prod"
    assert out[0]["transport"] == "remote-acp"
    assert out[0]["created_via"] == "config"


def test_agents_auto_migrates_legacy_agent_block(monkeypatch):
    monkeypatch.setattr(config, "CONFIG", {
        "agent": {
            "command": ["hermes", "chat", "-q", "{query}", "--yolo"],
            "label": "Hermes",
            "timeout_seconds": 200,
            "description": "Hermes backend",
        },
    })

    out = config.agents()

    assert len(out) == 1
    a = out[0]
    assert a["id"] == "local-default"
    assert a["transport"] == "local-acp"
    assert a["type"] == "hermes"
    assert a["label"] == "Hermes"
    assert a["created_via"] == "config"
    assert a["enabled"] is True


def test_agents_returns_empty_when_neither_present(monkeypatch):
    monkeypatch.setattr(config, "CONFIG", {})
    assert config.agents() == []


def test_agents_modern_list_overrides_legacy_when_both_present(monkeypatch):
    """If a config carries both, the modern list wins (the legacy block is
    treated as already-migrated to the modern list and ignored)."""
    monkeypatch.setattr(config, "CONFIG", {
        "agent": {"command": ["hermes"], "label": "Legacy"},
        "agents": [{"id": "modern", "label": "Modern", "transport": "local-acp"}],
    })

    out = config.agents()

    assert len(out) == 1
    assert out[0]["id"] == "modern"


def test_agents_normalises_defaults(monkeypatch):
    """Modern entries get sensible defaults for optional fields."""
    monkeypatch.setattr(config, "CONFIG", {
        "agents": [{"id": "x", "label": "X"}],  # transport missing
    })

    out = config.agents()

    assert out[0]["transport"] == "local-acp"
    assert out[0]["type"] == "hermes"
    assert out[0]["enabled"] is True
    assert out[0]["created_via"] == "config"
