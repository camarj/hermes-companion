"""AC-W1-U4 backend half — /api/agents/<id>/{skills,mcp,tools,config}.

The dispatcher chooses local CLI execution vs HTTP proxy based on the
agent's transport. Tests fake both legs hermetically.
"""

from __future__ import annotations

import httpx
import pytest

import host_mode


# ---------------------------------------------------------------------------
# Helpers — install fakes for the local CLI runner and the remote HTTP client.
# ---------------------------------------------------------------------------


def _fake_local_runner(monkeypatch, mapping: dict[tuple[str, ...], dict]):
    """Replace host_mode._run_hermes_cli with a lookup-based fake."""
    seen: list[tuple[str, ...]] = []

    async def _run(args):
        argv = tuple(args)
        seen.append(argv)
        if argv not in mapping:
            raise AssertionError(f"unexpected hermes argv: {argv}")
        return mapping[argv]

    monkeypatch.setattr(host_mode, "_run_hermes_cli", _run)
    return seen


def _fake_remote_http(monkeypatch, response_for: dict[str, dict]):
    """Replace httpx.AsyncClient with a MockTransport that maps URL → JSON."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        key = str(request.url)
        if key in response_for:
            spec = response_for[key]
            return httpx.Response(spec.get("status", 200), json=spec["body"])
        return httpx.Response(404, json={"detail": "not in mock"})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    class _PatchedClient(real):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", transport)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _PatchedClient)
    return recorded


# ---------------------------------------------------------------------------
# GET /api/agents/{id}/skills — local + remote dispatch
# ---------------------------------------------------------------------------


def _seed_remote_agent(client) -> dict:
    """Create a remote-acp agent via the existing CRUD endpoint."""
    resp = client.post(
        "/api/agents",
        json={
            "id": "vps-prod",
            "label": "Hermes VPS",
            "transport": "remote-acp",
            "transport_config": {
                "url": "wss://vps.example.com/api/host/acp",
                "token": "T-remote",
            },
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestSkillsEndpoint:
    def test_404_when_agent_does_not_exist(self, client):
        resp = client.get("/api/agents/nope/skills")
        assert resp.status_code == 404

    def test_local_dispatch_runs_hermes_cli(self, client, monkeypatch):
        seen = _fake_local_runner(monkeypatch, {
            ("skills", "list"): {
                "stdout": "kanban\nweb-research\n",
                "stderr": "",
                "exit_code": 0,
            },
        })
        resp = client.get("/api/agents/default/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert "kanban" in body["stdout"]
        assert seen == [("skills", "list")]

    def test_remote_dispatch_proxies_http_with_bearer(self, client, monkeypatch):
        _seed_remote_agent(client)
        recorded = _fake_remote_http(monkeypatch, {
            "https://vps.example.com/api/host/skills": {
                "body": {
                    "stdout": "remote-skill\n",
                    "stderr": "",
                    "exit_code": 0,
                },
            },
        })
        resp = client.get("/api/agents/vps-prod/skills")
        assert resp.status_code == 200
        assert "remote-skill" in resp.json()["stdout"]
        assert len(recorded) == 1
        assert recorded[0].headers["Authorization"] == "Bearer T-remote"

    def test_local_cli_failure_surfaces_502(self, client, monkeypatch):
        _fake_local_runner(monkeypatch, {
            ("skills", "list"): {
                "stdout": "",
                "stderr": "hermes: command not found",
                "exit_code": 127,
            },
        })
        resp = client.get("/api/agents/default/skills")
        assert resp.status_code == 502
        assert "command not found" in resp.json()["detail"]["stderr"]

    def test_remote_http_failure_surfaces_502(self, client, monkeypatch):
        _seed_remote_agent(client)
        _fake_remote_http(monkeypatch, {
            "https://vps.example.com/api/host/skills": {
                "status": 401,
                "body": {"detail": "invalid host token"},
            },
        })
        resp = client.get("/api/agents/vps-prod/skills")
        assert resp.status_code == 502
        # Bubbled-up detail comes from the host's own response.
        assert resp.json()["detail"]["detail"] == "invalid host token"


# ---------------------------------------------------------------------------
# Parametric coverage for the other three subcommands (mcp / tools / config).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,local_argv",
    [
        ("mcp", ("mcp", "list")),
        ("tools", ("tools", "--summary")),
        ("config", ("config", "show")),
    ],
)
def test_other_inspection_endpoints_dispatch_to_correct_local_argv(
    client, monkeypatch, kind, local_argv,
):
    seen = _fake_local_runner(monkeypatch, {
        local_argv: {"stdout": f"{kind}-ok\n", "stderr": "", "exit_code": 0},
    })
    resp = client.get(f"/api/agents/default/{kind}")
    assert resp.status_code == 200
    assert resp.json()["stdout"] == f"{kind}-ok\n"
    assert seen == [local_argv]


@pytest.mark.parametrize("kind", ["mcp", "tools", "config"])
def test_other_inspection_endpoints_proxy_remote(client, monkeypatch, kind):
    _seed_remote_agent(client)
    recorded = _fake_remote_http(monkeypatch, {
        f"https://vps.example.com/api/host/{kind}": {
            "body": {"stdout": f"remote-{kind}\n", "stderr": "", "exit_code": 0},
        },
    })
    resp = client.get(f"/api/agents/vps-prod/{kind}")
    assert resp.status_code == 200
    assert resp.json()["stdout"] == f"remote-{kind}\n"
    assert len(recorded) == 1
    assert recorded[0].headers["Authorization"] == "Bearer T-remote"


# ---------------------------------------------------------------------------
# PUT /api/agents/{id}/system-prompt (cycle C)
# ---------------------------------------------------------------------------


class TestSystemPromptEndpoint:
    def test_persists_new_value(self, client):
        resp = client.put(
            "/api/agents/default/system-prompt",
            json={"system_prompt": "You are terse."},
        )
        assert resp.status_code == 200
        assert resp.json()["system_prompt_override"] == "You are terse."

        # And the row reflects it on subsequent GET.
        agents = client.get("/api/agents").json()["agents"]
        default = next(a for a in agents if a["id"] == "default")
        assert default["system_prompt_override"] == "You are terse."

    def test_empty_string_clears_runtime_effect(self, client):
        client.put(
            "/api/agents/default/system-prompt",
            json={"system_prompt": "first"},
        )
        resp = client.put(
            "/api/agents/default/system-prompt",
            json={"system_prompt": "   "},
        )
        assert resp.status_code == 200
        assert resp.json()["system_prompt_override"] == ""

    def test_404_unknown_agent(self, client):
        resp = client.put(
            "/api/agents/nope/system-prompt",
            json={"system_prompt": "x"},
        )
        assert resp.status_code == 404

    def test_422_when_field_missing(self, client):
        resp = client.put(
            "/api/agents/default/system-prompt",
            json={},
        )
        assert resp.status_code == 422

    def test_422_when_field_wrong_type(self, client):
        resp = client.put(
            "/api/agents/default/system-prompt",
            json={"system_prompt": 42},
        )
        assert resp.status_code == 422
