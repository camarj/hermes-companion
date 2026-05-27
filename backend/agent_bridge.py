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
import re

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
    # Force unbuffered stdout so `hermes chat -q` tool-preview lines reach us
    # in real time instead of arriving in a 4KB chunk at process exit.
    env["PYTHONUNBUFFERED"] = "1"
    return env


# `hermes chat -q` wraps its final answer in a banner box. The opener carries
# the agent name (e.g. " ─  ⚕ Hermes  ─...─ "); the closer is just dashes
# and whitespace. We distinguish them by requiring a non-dash, non-whitespace
# character between the leading and trailing dashes for the opener.
_BANNER_OPEN_RE = re.compile(r"─.*[^\s─].*─")
_BANNER_CLOSE_RE = re.compile(r"^[\s─]+$")
_TOOL_LINE_RE = re.compile(r"^\s*┊\s*(.+?)\s*$")
# Lines inside the answer box are indented with 5 spaces; we dedent on extract.
_ANSWER_INDENT = "     "


def _is_banner_open(line: str) -> bool:
    return "─" in line and _BANNER_OPEN_RE.search(line) is not None


def _is_banner_close(line: str) -> bool:
    return "─" in line and _BANNER_CLOSE_RE.match(line) is not None and len(line.strip()) >= 10


def _dedent_answer_line(line: str) -> str:
    if line.startswith(_ANSWER_INDENT):
        return line[len(_ANSWER_INDENT):].rstrip()
    return line.rstrip()


def _clean_for_chat(answer: str) -> str:
    """Strip fenced code blocks. Used by the voice path so TTS doesn't read
    backticks aloud. The chat path renders markdown and keeps code fences."""
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


def _parse_hermes_output(stdout: str) -> tuple[list[str], str]:
    """Parse `hermes chat -q` output into (tool_previews, answer_text).

    The format is:
        Query: ...
        Initializing agent...
        ────────────────────         (initial separator — ignored)

          ┊ 💻 $ <cmd>  0.5s         (zero or more tool previews)
         ─  ⚕ Hermes  ─...─          (banner open: marks start of answer)
             <answer line>
             ...
         ─────────────────────       (banner close)

        Resume this session with: ...
        Session: ...                 (metadata — ignored)

    If no banner is detected we fall back to the raw stdout so older modes
    like `hermes -z` (which emits the answer as a clean blob) still work.
    """
    previews: list[str] = []
    answer_lines: list[str] = []
    phase = "preamble"
    saw_banner = False
    for line in stdout.splitlines():
        if phase == "preamble":
            if _is_banner_open(line):
                phase = "answer"
                saw_banner = True
                continue
            m = _TOOL_LINE_RE.match(line)
            if m:
                phase = "tools"
                previews.append(m.group(1).strip())
            continue
        if phase == "tools":
            if _is_banner_open(line):
                phase = "answer"
                saw_banner = True
                continue
            m = _TOOL_LINE_RE.match(line)
            if m:
                previews.append(m.group(1).strip())
            continue
        if phase == "answer":
            if _is_banner_close(line):
                phase = "done"
                continue
            answer_lines.append(_dedent_answer_line(line))
            continue
    if not saw_banner:
        return [], stdout.strip()
    return previews, "\n".join(answer_lines).strip()


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

    _, answer = _parse_hermes_output(stdout_text)
    cleaned = _clean_for_chat(answer)
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
    """Run the agent and yield (kind, text) tuples in real time.

    `kind` is `"text"` for the final answer (rendered as the assistant
    bubble) and `"reasoning"` for intermediate chain-of-thought (rendered
    as a collapsible thinking block).

    Reads `hermes chat -q` line-by-line, parses tool previews into reasoning
    events and the banner-wrapped answer body into text events. If no banner
    is detected (older `hermes -z` mode, or unrelated agent) the whole
    stdout is yielded as text at the end as a fallback.
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

    # Drain stderr concurrently — leaving it unread can deadlock the
    # subprocess if it writes more than the pipe buffer holds.
    stderr_buf: list[bytes] = []

    async def _drain_stderr():
        try:
            while True:
                chunk = await proc.stderr.readline()
                if not chunk:
                    return
                stderr_buf.append(chunk)
        except Exception:
            return

    stderr_task = asyncio.create_task(_drain_stderr())

    # Total-runtime watchdog. The line-by-line reader has no per-line timeout
    # because Hermes can take many seconds between tool previews; we cap the
    # whole turn instead.
    timeout = agent_timeout()
    timed_out = False

    async def _watchdog():
        nonlocal timed_out
        await asyncio.sleep(timeout)
        if proc.returncode is None:
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass

    watchdog_task = asyncio.create_task(_watchdog())

    phase = "preamble"
    saw_banner = False
    raw_lines: list[str] = []
    answer_started = False
    skipped_first_blank = False

    try:
        while True:
            try:
                line_b = await proc.stdout.readline()
            except Exception as exc:
                print(f"{log_prefix} stdout read error: {exc}")
                break
            if not line_b:
                break
            # Hermes emits CRLF when piped; strip both so trailing \r doesn't
            # break our end-of-line regex anchors.
            line = line_b.decode("utf-8", errors="replace").rstrip("\r\n")
            raw_lines.append(line)

            if phase == "preamble":
                if _is_banner_open(line):
                    phase = "answer"
                    saw_banner = True
                    continue
                m = _TOOL_LINE_RE.match(line)
                if m:
                    phase = "tools"
                    yield ("reasoning", m.group(1).strip())
                continue

            if phase == "tools":
                if _is_banner_open(line):
                    phase = "answer"
                    saw_banner = True
                    continue
                m = _TOOL_LINE_RE.match(line)
                if m:
                    yield ("reasoning", m.group(1).strip())
                continue

            if phase == "answer":
                if _is_banner_close(line):
                    phase = "done"
                    continue
                content = _dedent_answer_line(line)
                # Hermes pads the box with a blank line on top; skip just the
                # first one so the bubble doesn't start with a stray newline.
                if not answer_started and not content and not skipped_first_blank:
                    skipped_first_blank = True
                    continue
                answer_started = True
                yield ("text", content + "\n")
                continue
    finally:
        watchdog_task.cancel()
        try:
            await proc.wait()
        except Exception:
            pass
        stderr_task.cancel()

    if timed_out:
        print(f"{log_prefix} timeout after {timeout}s")
        yield ("text", "\n\n[The agent took too long to respond.]")
        return

    if not saw_banner:
        # `hermes -z` mode (or unrelated agent): no banner was emitted, so
        # the whole stdout we accumulated is the answer.
        fallback = "\n".join(raw_lines).strip()
        if fallback:
            print(f"{log_prefix} no banner detected; emitting {len(fallback)} chars as text")
            yield ("text", fallback)
        else:
            stderr_text = b"".join(stderr_buf).decode("utf-8", errors="replace")[:200]
            print(f"{log_prefix} empty stdout (exit={proc.returncode}). stderr={stderr_text}")
            yield ("text", "The agent returned no answer.")


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
