from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from unittest import mock

from claude_companion.account import AccountBinding, AccountMismatch


class AccountBindingTests(unittest.TestCase):
    def test_default_clears_inherited_other_profile_without_mutating_parent(self) -> None:
        original = {"CLAUDE_CONFIG_DIR": "/other", "ANTHROPIC_API_KEY": "secret", "CLAUDECODE": "1"}
        env = AccountBinding("default", "personal@example.com").environment(original)
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertEqual(original["CLAUDE_CONFIG_DIR"], "/other")

    def test_explicit_binding_overrides_environment(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            binding = AccountBinding.resolve(home, "work@example.com", {
                "CLAUDE_COMPANION_CONFIG_DIR": "default", "CLAUDE_COMPANION_ACCOUNT": "personal@example.com",
            })
            self.assertEqual(binding.environment({})["CLAUDE_CONFIG_DIR"], home)
            self.assertEqual(binding.expected_email, "work@example.com")

    def test_mismatched_or_signed_out_identity_fails_before_dispatch(self) -> None:
        binding = AccountBinding("default", "expected@example.com")
        for value in ({"loggedIn": True, "email": "other@example.com"}, {"loggedIn": False}, []):
            result = subprocess.CompletedProcess([], 0, json.dumps(value), "")
            with mock.patch("claude_companion.account.subprocess.run", return_value=result):
                with self.assertRaises(AccountMismatch):
                    binding.verify("claude", {})

    def test_matching_identity_uses_selected_child_environment(self) -> None:
        result = subprocess.CompletedProcess([], 0, '{"loggedIn":true,"email":"work@example.com"}', "")
        with mock.patch("claude_companion.account.subprocess.run", return_value=result) as run:
            self.assertEqual(AccountBinding(expected_email="WORK@example.com").verify("claude", {"CLAUDE_CONFIG_DIR": "/work"}), "work@example.com")
            self.assertEqual(run.call_args.kwargs["env"], {"CLAUDE_CONFIG_DIR": "/work"})


if __name__ == "__main__":
    unittest.main()
