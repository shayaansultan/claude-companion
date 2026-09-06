"""`claude-companion setup`: is this machine ready to run the companion?"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field

from . import __version__

CODEX_CONFIG = os.path.expanduser("~/.codex/config.toml")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def as_dict(self) -> dict:
        return {
            "version": __version__,
            "ok": self.ok,
            "checks": [c.__dict__ for c in self.checks],
        }


def _run(argv: list[str], timeout: float = 20) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_claude() -> list[Check]:
    exe = shutil.which("claude")
    if not exe:
        return [
            Check(
                "claude CLI",
                False,
                "`claude` is not on PATH.",
                "Install Claude Code: https://docs.claude.com/en/docs/claude-code/setup",
            )
        ]
    version = _run([exe, "--version"])
    version_text = version.stdout.strip() if version and version.returncode == 0 else "version unknown"
    checks = [Check("claude CLI", True, f"{exe} ({version_text})")]

    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    try:
        status = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired):
        status = None
    logged_in = False
    detail = "no output from `claude auth status`"
    if status is not None:
        try:
            info = json.loads(status.stdout)
            logged_in = bool(info.get("loggedIn"))
            who = info.get("email") or info.get("authMethod") or "unknown account"
            plan = info.get("subscriptionType")
            detail = f"logged in as {who}{f' ({plan})' if plan else ''}" if logged_in else "not logged in"
        except (json.JSONDecodeError, AttributeError):
            detail = (status.stdout or status.stderr).strip().splitlines()[0] if (status.stdout or status.stderr).strip() else detail
    checks.append(
        Check(
            "claude auth",
            logged_in,
            detail,
            None if logged_in else "Run `claude auth login` in a terminal, then re-run setup.",
        )
    )
    return checks


def check_sandbox_network() -> Check:
    """Codex runs this script inside its workspace-write sandbox. Claude needs
    the network from in there, which is off unless the config says otherwise."""
    if not os.path.exists(CODEX_CONFIG):
        return Check(
            "codex sandbox network",
            False,
            f"{CODEX_CONFIG} not found.",
            "Add to ~/.codex/config.toml:\n\n[sandbox_workspace_write]\nnetwork_access = true",
        )
    try:
        with open(CODEX_CONFIG, "rb") as fh:
            config = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return Check("codex sandbox network", False, f"Could not parse {CODEX_CONFIG}: {exc}")
    enabled = bool((config.get("sandbox_workspace_write") or {}).get("network_access"))
    return Check(
        "codex sandbox network",
        enabled,
        "sandbox_workspace_write.network_access = true" if enabled else "sandbox_workspace_write.network_access is not set",
        None
        if enabled
        else "Add to ~/.codex/config.toml so Claude can reach the API from inside Codex's sandbox:\n\n"
        "[sandbox_workspace_write]\nnetwork_access = true",
    )


def check_git() -> Check:
    exe = shutil.which("git")
    return Check("git", bool(exe), exe or "`git` is not on PATH.", None if exe else "Install Git.")


def run_checks() -> Report:
    report = Report()
    report.checks.append(check_git())
    report.checks.extend(check_claude())
    report.checks.append(check_sandbox_network())
    return report


def render_report(report: Report) -> str:
    lines = [f"# Claude Companion setup (v{__version__})", ""]
    for c in report.checks:
        lines.append(f"- {'OK  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
        if not c.ok and c.fix:
            for i, fix_line in enumerate(c.fix.splitlines()):
                lines.append(f"       {fix_line}" if i else f"       Fix: {fix_line}")
    lines.append("")
    lines.append("Ready." if report.ok else "Not ready. Apply the fixes above and re-run `claude-companion setup`.")
    return "\n".join(lines) + "\n"
