"""AC-W1-U4: /api/host/{skills,mcp,tools,config} read-only inspection.

Each endpoint wraps a `hermes` CLI subcommand. The subprocess is replaced
by a fake runner via monkeypatch so tests stay hermetic.
"""

import host_mode


def _fake_runner(monkeypatch, mapping: dict[tuple[str, ...], dict]):
    """Install a fake `_run_hermes_cli` keyed on the argv tuple it receives."""
    seen: list[tuple[str, ...]] = []

    async def _run(args):
        argv = tuple(args)
        seen.append(argv)
        if argv not in mapping:
            raise AssertionError(f"unexpected hermes args: {argv}")
        return mapping[argv]

    monkeypatch.setattr(host_mode, "_run_hermes_cli", _run)
    return seen


# ---------------------------------------------------------------------------
# GET /api/host/skills (cycle 1)
# ---------------------------------------------------------------------------


def test_skills_rejects_no_bearer(host_client):
    resp = host_client.get("/api/host/skills")
    assert resp.status_code == 401


def test_skills_rejects_invalid_bearer(host_client):
    resp = host_client.get(
        "/api/host/skills",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_skills_returns_cli_output_for_valid_bearer(host_client, monkeypatch):
    seen = _fake_runner(monkeypatch, {
        ("skills", "list"): {
            "stdout": "kanban\nweather\nweb-research\n",
            "stderr": "",
            "exit_code": 0,
        },
    })

    resp = host_client.get(
        "/api/host/skills",
        headers={"Authorization": "Bearer secret-T1"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["exit_code"] == 0
    assert "kanban" in body["stdout"]
    assert body["stderr"] == ""
    assert seen == [("skills", "list")]


def test_skills_surfaces_cli_failure_with_500(host_client, monkeypatch):
    _fake_runner(monkeypatch, {
        ("skills", "list"): {
            "stdout": "",
            "stderr": "hermes: command not found",
            "exit_code": 127,
        },
    })

    resp = host_client.get(
        "/api/host/skills",
        headers={"Authorization": "Bearer secret-T1"},
    )

    assert resp.status_code == 502
    body = resp.json()
    assert body["detail"]["exit_code"] == 127
    assert "command not found" in body["detail"]["stderr"]


# ---------------------------------------------------------------------------
# GET /api/host/mcp (cycle 2)
# ---------------------------------------------------------------------------


def test_mcp_rejects_no_bearer(host_client):
    assert host_client.get("/api/host/mcp").status_code == 401


def test_mcp_returns_cli_output(host_client, monkeypatch):
    seen = _fake_runner(monkeypatch, {
        ("mcp", "list"): {
            "stdout": "filesystem\ngithub\n",
            "stderr": "",
            "exit_code": 0,
        },
    })

    resp = host_client.get(
        "/api/host/mcp",
        headers={"Authorization": "Bearer secret-T1"},
    )

    assert resp.status_code == 200
    assert "github" in resp.json()["stdout"]
    assert seen == [("mcp", "list")]


# ---------------------------------------------------------------------------
# GET /api/host/tools (cycle 3)
# ---------------------------------------------------------------------------


def test_tools_rejects_no_bearer(host_client):
    assert host_client.get("/api/host/tools").status_code == 401


def test_tools_returns_cli_output(host_client, monkeypatch):
    seen = _fake_runner(monkeypatch, {
        ("tools", "--summary"): {
            "stdout": "bash: on\npython: on\n",
            "stderr": "",
            "exit_code": 0,
        },
    })

    resp = host_client.get(
        "/api/host/tools",
        headers={"Authorization": "Bearer secret-T1"},
    )

    assert resp.status_code == 200
    assert "python" in resp.json()["stdout"]
    assert seen == [("tools", "--summary")]


# ---------------------------------------------------------------------------
# GET /api/host/config (cycle 4)
# ---------------------------------------------------------------------------


def test_config_rejects_no_bearer(host_client):
    assert host_client.get("/api/host/config").status_code == 401


def test_config_returns_cli_output(host_client, monkeypatch):
    seen = _fake_runner(monkeypatch, {
        ("config", "show"): {
            "stdout": "model: claude-sonnet-4-5\n",
            "stderr": "",
            "exit_code": 0,
        },
    })

    resp = host_client.get(
        "/api/host/config",
        headers={"Authorization": "Bearer secret-T1"},
    )

    assert resp.status_code == 200
    assert "claude-sonnet" in resp.json()["stdout"]
    assert seen == [("config", "show")]


# ---------------------------------------------------------------------------
# POST /api/host/upload (cycle 5, AC-W1-R4 precondition)
# ---------------------------------------------------------------------------


def test_upload_rejects_no_bearer(host_client):
    resp = host_client.post(
        "/api/host/upload",
        files={"file": ("a.png", b"\x89PNG\r\n", "image/png")},
    )
    assert resp.status_code == 401


def test_upload_persists_payload_and_returns_handle(
    host_client, monkeypatch, tmp_path,
):
    monkeypatch.setattr(host_mode, "_upload_dir", lambda: tmp_path)

    payload = b"\x89PNG\r\n\x1a\nfakebody"
    resp = host_client.post(
        "/api/host/upload",
        headers={"Authorization": "Bearer secret-T1"},
        files={"file": ("frame.png", payload, "image/png")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["size"] == len(payload)
    assert body["mime_type"] == "image/png"
    handle = body["handle"]
    assert handle.startswith(str(tmp_path))

    from pathlib import Path
    assert Path(handle).read_bytes() == payload


def test_upload_rejects_payload_above_cap(host_client, monkeypatch, tmp_path):
    monkeypatch.setattr(host_mode, "_upload_dir", lambda: tmp_path)
    monkeypatch.setattr(host_mode, "_UPLOAD_MAX_BYTES", 16)

    resp = host_client.post(
        "/api/host/upload",
        headers={"Authorization": "Bearer secret-T1"},
        files={"file": ("big.bin", b"x" * 64, "application/octet-stream")},
    )

    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# POST /api/host/config/system-prompt (cycle 6, AC-W1-U5 backend half)
# ---------------------------------------------------------------------------


def test_system_prompt_rejects_no_bearer(host_client):
    resp = host_client.post(
        "/api/host/config/system-prompt",
        json={"system_prompt": "be terse"},
    )
    assert resp.status_code == 401


def test_system_prompt_writes_agents_md_and_returns_cwd(
    host_client, monkeypatch, tmp_path,
):
    monkeypatch.setattr(host_mode, "_upload_dir", lambda: tmp_path)

    prompt = "You are a senior architect. Speak in short sentences."
    resp = host_client.post(
        "/api/host/config/system-prompt",
        headers={"Authorization": "Bearer secret-T1"},
        json={"system_prompt": prompt},
    )

    assert resp.status_code == 200
    body = resp.json()
    cwd = body["cwd"]

    from pathlib import Path
    cwd_path = Path(cwd)
    assert cwd_path.is_dir()
    assert cwd_path.parent == tmp_path
    agents_md = cwd_path / "AGENTS.md"
    assert agents_md.is_file()
    assert agents_md.read_text(encoding="utf-8") == prompt


def test_system_prompt_rejects_empty_body(host_client):
    resp = host_client.post(
        "/api/host/config/system-prompt",
        headers={"Authorization": "Bearer secret-T1"},
        json={"system_prompt": "   "},
    )
    assert resp.status_code == 400


def test_system_prompt_rejects_missing_field(host_client):
    resp = host_client.post(
        "/api/host/config/system-prompt",
        headers={"Authorization": "Bearer secret-T1"},
        json={},
    )
    assert resp.status_code == 422
