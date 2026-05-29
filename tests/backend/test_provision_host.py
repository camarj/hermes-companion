"""AC-W1-R6: host provisioning seeds a bearer token idempotently.

`provision_host` is the testable core of the host-mode installer. The bash
wrapper (`install-host.sh`) handles environment bootstrap (clone, venv, pip);
the token generation and the idempotent `config.yaml` merge live here so they
can be exercised under pytest rather than as a manual ops step.
"""

from pathlib import Path

import yaml

import provision_host


def test_generate_token_is_long_and_unique() -> None:
    a = provision_host.generate_token()
    b = provision_host.generate_token()
    assert len(a) >= 32
    assert a.isalnum()
    assert a != b


def test_ensure_host_token_adds_entry_when_label_absent() -> None:
    config: dict = {}
    updated, token, created = provision_host.ensure_host_token(
        config, label="vps-prod", token="abc123"
    )
    assert created is True
    assert token == "abc123"
    assert updated["host_tokens"] == [{"token": "abc123", "label": "vps-prod"}]


def test_ensure_host_token_is_idempotent_for_same_label() -> None:
    config = {"host_tokens": [{"token": "existing", "label": "vps-prod"}]}
    updated, token, created = provision_host.ensure_host_token(
        config, label="vps-prod", token="new-one"
    )
    assert created is False
    assert token == "existing"
    assert updated["host_tokens"] == [{"token": "existing", "label": "vps-prod"}]


def test_ensure_host_token_appends_distinct_labels() -> None:
    config = {"host_tokens": [{"token": "t1", "label": "vps-prod"}]}
    updated, _, created = provision_host.ensure_host_token(
        config, label="laptop-dev", token="t2"
    )
    assert created is True
    assert len(updated["host_tokens"]) == 2
    labels = {e["label"] for e in updated["host_tokens"]}
    assert labels == {"vps-prod", "laptop-dev"}


def test_provision_writes_config_then_reruns_idempotently(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"

    result = provision_host.provision(config_path, label="vps-prod")
    assert config_path.exists()
    written = yaml.safe_load(config_path.read_text())
    tokens = written["host_tokens"]
    assert len(tokens) == 1
    assert tokens[0]["label"] == "vps-prod"
    assert len(tokens[0]["token"]) >= 32
    assert result.created is True
    assert result.token == tokens[0]["token"]

    # Re-run: same label must reuse the token and not duplicate the entry.
    again = provision_host.provision(config_path, label="vps-prod")
    rewritten = yaml.safe_load(config_path.read_text())
    assert len(rewritten["host_tokens"]) == 1
    assert again.created is False
    assert again.token == result.token


def test_provision_merges_into_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"assistant_name": "Companion"}))

    result = provision_host.provision(config_path, label="vps-prod")
    written = yaml.safe_load(config_path.read_text())
    assert written["assistant_name"] == "Companion"
    assert written["host_tokens"][0]["label"] == "vps-prod"
    assert result.created is True
