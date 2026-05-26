"""
Pluggable external-agent bridge.

The assistant invokes the `call_agent` tool when the model decides a question
needs live data or real-world action. This module runs whatever subprocess the
user configured under `agent.command` in config.yaml and returns its stdout
as the answer.

Defaults to `hermes -z {query} --yolo` but works with any CLI: the literal
strings "{query}" and "{user_id}" inside `agent.command` are substituted at
runtime, and the requester identity is also exposed via env vars:
  AGENT_REQUESTER_ID, AGENT_REQUESTER_NAME, AGENT_REQUESTER_ROLE
"""

from __future__ import annotations

import asyncio
import os

from config import agent_command, agent_timeout, agent_enabled


def _resolve_command(query: str, user_id: str) -> list[str]:
    cmd = agent_command()
    return [
        arg.replace("{query}", query).replace("{user_id}", user_id)
        for arg in cmd
    ]


def _build_env(user_id: str, user_name: str, user_role: str) -> dict[str, str]:
    env = os.environ.copy()
    env["AGENT_REQUESTER_ID"] = user_id
    env["AGENT_REQUESTER_NAME"] = user_name
    if user_role:
        env["AGENT_REQUESTER_ROLE"] = user_role
    return env


def _clean_for_chat(answer: str) -> str:
    """Strip noisy markdown that doesn't render well in our chat UI.

    Keeps the message readable as plain text without dropping content. We
    don't try to be a full markdown renderer — just remove fenced code blocks
    which look bad raw.
    """
    if not answer:
        return ""
    out = []
    in_fence = False
    for line in answer.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        out.append(line)
    cleaned = "\n".join(out).strip()
    return cleaned or answer.strip()


async def call_agent(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    log_prefix: str = "[agent]",
) -> str:
    """Invoke the configured agent subprocess and return its answer."""
    if not agent_enabled():
        return "No external agent is configured. Set `agent.command` in config.yaml."

    argv = _resolve_command(query, user_id)
    print(f"{log_prefix} invoking {argv[0]} (requester={user_id}): {query[:80]}")

    env = _build_env(user_id, user_name, user_role)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        print(f"{log_prefix} binary not found: {argv[0]}")
        return f"Couldn't reach the external agent ({argv[0]} not found)."
    except Exception as e:
        print(f"{log_prefix} spawn error: {e}")
        return "Couldn't start the external agent."

    timeout = agent_timeout()
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        print(f"{log_prefix} timeout after {timeout}s")
        return "The agent took too long to respond."

    stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_b.decode("utf-8", errors="replace").strip()

    # Some agents (e.g. Hermes) occasionally exit with SIGABRT after writing
    # a valid answer to stdout. Prefer stdout if non-empty regardless of
    # returncode; treat empty stdout as a real failure.
    if not stdout_text:
        print(f"{log_prefix} empty stdout (exit={proc.returncode}). stderr={stderr_text[:200]}")
        return "The agent returned no answer."

    if proc.returncode != 0:
        print(
            f"{log_prefix} exited with code {proc.returncode} but stdout is valid; "
            f"using it. stderr={stderr_text[:200]}"
        )

    cleaned = _clean_for_chat(stdout_text)
    print(f"{log_prefix} answer ({len(cleaned)} chars): {cleaned[:140]}")
    return cleaned or "The agent returned no answer."


async def call_agent_stream(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    log_prefix: str = "[agent/stream]",
):
    """Run the agent and yield (kind, text) tuples.

    `kind` is `"reasoning"` for non-final paragraphs (intermediate chain-of-
    thought) and `"text"` for the final paragraph (the answer). Splitting
    happens on blank lines in the agent's stdout — by convention, the last
    paragraph is the answer.

    The current implementation buffers the entire subprocess output before
    yielding, because `hermes -z` emits one blob; future variants (e.g.
    `hermes chat -q`) can be wired to stream paragraph-by-paragraph as the
    output lands.
    """
    if not agent_enabled():
        yield ("text", "No external agent is configured. Set `agent.command` in config.yaml.")
        return

    argv = _resolve_command(query, user_id)
    print(f"{log_prefix} invoking {argv[0]} (requester={user_id}): {query[:80]}")
    env = _build_env(user_id, user_name, user_role)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        print(f"{log_prefix} binary not found: {argv[0]}")
        yield ("text", f"Couldn't reach the external agent ({argv[0]} not found).")
        return
    except Exception as e:
        print(f"{log_prefix} spawn error: {e}")
        yield ("text", "Couldn't start the external agent.")
        return

    timeout = agent_timeout()
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        print(f"{log_prefix} timeout after {timeout}s")
        yield ("text", "The agent took too long to respond.")
        return

    stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_b.decode("utf-8", errors="replace").strip()

    if not stdout_text:
        print(f"{log_prefix} empty stdout (exit={proc.returncode}). stderr={stderr_text[:200]}")
        yield ("text", "The agent returned no answer.")
        return

    if proc.returncode != 0:
        print(
            f"{log_prefix} exited with code {proc.returncode} but stdout is valid; "
            f"using it. stderr={stderr_text[:200]}"
        )

    cleaned = _clean_for_chat(stdout_text)
    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    if not paragraphs:
        yield ("text", cleaned)
        return

    print(f"{log_prefix} answer in {len(paragraphs)} paragraph(s); last → text, rest → reasoning")
    for p in paragraphs[:-1]:
        yield ("reasoning", p)
    yield ("text", paragraphs[-1])


async def call_agent_for_voice(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
) -> str:
    """Voice variant: flattens bullets/headings into a single line so TTS
    doesn't stutter on markdown punctuation."""
    answer = await call_agent(
        query,
        user_name=user_name,
        user_id=user_id,
        user_role=user_role,
        log_prefix="[realtime/agent]",
    )
    cleaned_lines = []
    for line in answer.splitlines():
        s = line.strip()
        if not s:
            continue
        while s and s[0] in "-*#> ":
            s = s[1:].lstrip()
        cleaned_lines.append(s)
    return (" ".join(cleaned_lines)).strip() or answer
