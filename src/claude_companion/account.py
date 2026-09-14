"""Select a Claude login without mutating the caller's global account."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class AccountMismatch(RuntimeError):
    """The selected home does not hold the expected Claude identity."""


@dataclass(frozen=True)
class AccountBinding:
    config_dir: str | None = None
    expected_email: str | None = None

    @classmethod
    def resolve(
        cls,
        config_dir: str | None = None,
        expected_email: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> AccountBinding:
        source = os.environ if environ is None else environ
        return cls(
            config_dir=config_dir or source.get("CLAUDE_COMPANION_CONFIG_DIR"),
            expected_email=expected_email or source.get("CLAUDE_COMPANION_ACCOUNT"),
        )

    def environment(self, inherited: Mapping[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ if inherited is None else inherited)
        env.pop("CLAUDECODE", None)

        match self.config_dir:
            case None:
                pass
            case "default":
                env.pop("CLAUDE_CONFIG_DIR", None)
            case directory:
                home = Path(directory).expanduser()
                if not home.is_absolute() or not home.is_dir():
                    raise AccountMismatch("The selected Claude config directory does not exist.")
                env["CLAUDE_CONFIG_DIR"] = str(home)

        if self.expected_email:
            # An explicit subscription binding must not accidentally inherit API
            # billing or a different OAuth token from the calling shell.
            for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL"):
                env.pop(key, None)

        return env

    def verify(self, executable: str, env: Mapping[str, str]) -> str | None:
        if not self.expected_email:
            return None

        try:
            result = subprocess.run(
                [executable, "auth", "status", "--json"],
                env=dict(env), capture_output=True, text=True, timeout=20,
            )
            value: object = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            raise AccountMismatch("Could not verify the selected Claude login; no task was dispatched.") from error

        identity = value if isinstance(value, dict) else {}
        email = identity.get("email")
        matches = (
            result.returncode == 0
            and identity.get("loggedIn") is True
            and isinstance(email, str)
            and email.casefold() == self.expected_email.casefold()
        )

        if not matches:
            raise AccountMismatch(
                f"Selected Claude login does not match {self.expected_email}; no task was dispatched. "
                "Sign the selected home into the intended account or correct its profile binding."
            )

        return email
