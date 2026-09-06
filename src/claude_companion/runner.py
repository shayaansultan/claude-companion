"""Spawn `claude -p` and parse its JSON output."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

EFFORTS = ("low", "medium", "high", "xhigh", "max")
PERMISSION_MODES = ("plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "manual")

# Keep every run hermetic: no user MCP servers (slow to start and irrelevant
# to a review), no session files left behind. Never use --bare here: it skips
# the keychain read and reports "Not logged in".
BASE_ARGS = ["-p", "--output-format", "json", "--strict-mcp-config", "--no-session-persistence"]


class ClaudeUnavailable(RuntimeError):
    pass


def find_claude() -> str | None:
    return shutil.which("claude")


@dataclass
class ClaudeResult:
    ok: bool
    text: str = ""
    structured: Any = None
    error: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    models: list[str] = field(default_factory=list)
    returncode: int = 0
    stderr: str = ""
    argv: list[str] = field(default_factory=list)


def build_argv(
    *,
    permission_mode: str,
    model: str | None = None,
    effort: str | None = None,
    json_schema: dict | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    disallowed_tools: list[str] | None = None,
) -> list[str]:
    exe = find_claude()
    if not exe:
        raise ClaudeUnavailable("The `claude` CLI is not on PATH. Install Claude Code and run `claude auth login`.")
    argv = [exe, *BASE_ARGS, "--permission-mode", permission_mode]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    if json_schema is not None:
        argv += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    if max_turns:
        argv += ["--max-turns", str(max_turns)]
    if max_budget_usd:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    if disallowed_tools:
        argv += ["--disallowedTools", ",".join(disallowed_tools)]
    return argv


def _find_result_record(payload: Any) -> dict | None:
    if isinstance(payload, dict):
        return payload if payload.get("type") == "result" else None
    if isinstance(payload, list):
        for record in reversed(payload):
            if isinstance(record, dict) and record.get("type") == "result":
                return record
    return None


def run_claude(argv: list[str], prompt: str, *, cwd: str, timeout: float | None = None) -> ClaudeResult:
    """Run claude with the prompt on stdin and return the parsed result record."""
    env = dict(os.environ)
    # A parent Claude Code session marks its children; clearing it lets the
    # companion be tested from inside Claude Code as well as from Codex.
    env.pop("CLAUDECODE", None)
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ClaudeResult(ok=False, error=f"Claude did not finish within {timeout:.0f}s.", argv=argv)

    stderr = proc.stderr.strip()
    stdout = proc.stdout.strip()

    record: dict | None = None
    if stdout:
        try:
            record = _find_result_record(json.loads(stdout))
        except json.JSONDecodeError:
            # Some failures print a plain-text line before any JSON.
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        record = _find_result_record(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if record:
                        break

    if record is None:
        detail = stderr or stdout or f"claude exited with status {proc.returncode} and no output"
        return ClaudeResult(ok=False, error=detail, returncode=proc.returncode, stderr=stderr, argv=argv)

    text = record.get("result") or ""
    if not isinstance(text, str):
        text = json.dumps(text)
    result = ClaudeResult(
        ok=not record.get("is_error") and proc.returncode == 0,
        text=text,
        structured=record.get("structured_output"),
        cost_usd=record.get("total_cost_usd"),
        duration_ms=record.get("duration_ms"),
        num_turns=record.get("num_turns"),
        models=sorted((record.get("modelUsage") or {}).keys()),
        returncode=proc.returncode,
        stderr=stderr,
        argv=argv,
    )
    if not result.ok:
        result.error = text or stderr or record.get("subtype") or "Claude reported an error."
        if record.get("subtype") == "error_max_turns":
            result.error = "Claude hit the turn limit before finishing. Raise --max-turns or narrow the request."
    return result


def progress(message: str) -> None:
    """Progress lines go to stderr so stdout stays clean for the report."""
    print(f"claude-companion: {message}", file=sys.stderr, flush=True)
