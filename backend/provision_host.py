"""Host-mode provisioning core (AC-W1-R6, PRD §3.2.1).

Testable heart of the host installer: generate an unguessable bearer token and
merge it idempotently into a `config.yaml` under a label. The bash wrapper
(`install-host.sh`) bootstraps the environment (clone/pull, venv, pip) and then
calls `python -m provision_host` for this step.

Run directly:
    python -m provision_host --label vps-prod
"""

from __future__ import annotations

import argparse
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PORT = 8000


def generate_token() -> str:
    """A long, unguessable, alphanumeric bearer token (48 hex chars)."""
    return secrets.token_hex(24)


def ensure_host_token(
    config: dict[str, Any], *, label: str, token: str
) -> tuple[dict[str, Any], str, bool]:
    """Add a host token under `label` if absent. Idempotent by label.

    Returns `(config, effective_token, created)`. When an entry with the same
    label already exists, its token is reused and `created` is False — so a
    re-run never duplicates the entry or rotates the operator's token.
    """
    tokens: list[dict[str, Any]] = config.setdefault("host_tokens", [])
    for entry in tokens:
        if entry.get("label") == label:
            return config, entry["token"], False
    tokens.append({"token": token, "label": label})
    return config, token, True


def load_config(path: Path) -> dict[str, Any]:
    """Load an existing config.yaml, or start from an empty mapping."""
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text()) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} does not contain a YAML mapping")
    return loaded


def write_config(path: Path, config: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))


@dataclass
class ProvisionResult:
    token: str
    label: str
    created: bool
    config_path: Path


def provision(
    config_path: Path, *, label: str, token: str | None = None
) -> ProvisionResult:
    """Seed a host token into `config_path`, creating the file if needed."""
    config = load_config(config_path)
    config, effective, created = ensure_host_token(
        config, label=label, token=token or generate_token()
    )
    write_config(config_path, config)
    return ProvisionResult(
        token=effective, label=label, created=created, config_path=config_path
    )


def _acp_url(host: str, port: int) -> str:
    scheme = "wss" if port == 443 else "ws"
    netloc = host if port in (80, 443) else f"{host}:{port}"
    return f"{scheme}://{netloc}/api/host/acp"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="provision_host",
        description="Seed a host-mode bearer token into config.yaml.",
    )
    parser.add_argument(
        "--label", required=True, help="Label identifying this client/token."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml).",
    )
    parser.add_argument(
        "--host",
        default=socket.gethostname(),
        help="Public host the remote client will reach (for the printed URL).",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Public port (default: 8000)."
    )
    args = parser.parse_args(argv)

    result = provision(Path(args.config), label=args.label)
    url = _acp_url(args.host, args.port)
    status = "seeded new" if result.created else "reused existing"

    print(f"✓ {status} host token under label '{result.label}'")
    print(f"  config: {result.config_path}")
    print(f"  token:  {result.token}")
    print(f"  url:    {url}")
    print()
    print("Launch the host:")
    print("  HERMES_COMPANION_MODE=host ./start.sh")
    print()
    print("On the client, declare a remote-acp agent in config.yaml:")
    print(f'    transport_config: {{ url: "{url}", token: "env:HOST_TOKEN" }}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
