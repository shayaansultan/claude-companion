"""Command construction and output parsing, without spawning claude."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from claude_companion import runner


class BuildArgvTests(unittest.TestCase):
    def test_flags(self) -> None:
        with mock.patch.object(runner, "find_claude", return_value="/bin/claude"):
            argv = runner.build_argv(
                permission_mode="plan",
                model="fable",
                effort="high",
                json_schema={"type": "object"},
                max_turns=5,
                disallowed_tools=["Edit", "Write"],
            )
        self.assertEqual(argv[0], "/bin/claude")
        for flag in ("-p", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertNotIn("--bare", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "fable")
        self.assertEqual(argv[argv.index("--effort") + 1], "high")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "5")
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "Edit,Write")
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]), {"type": "object"})

    def test_missing_claude(self) -> None:
        with mock.patch.object(runner, "find_claude", return_value=None):
            with self.assertRaises(runner.ClaudeUnavailable):
                runner.build_argv(permission_mode="plan")


class FakeClaude(unittest.TestCase):
    """Run `run_claude` against a tiny script standing in for the claude binary."""

    def fake(self, body: str) -> str:
        path = os.path.join(self.tmp.name, "claude")
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parses_result_record_from_array(self) -> None:
        payload = [
            {"type": "system", "subtype": "init"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": '{"verdict":"approve"}',
                "structured_output": {"verdict": "approve"},
                "total_cost_usd": 0.5,
                "duration_ms": 1000,
                "num_turns": 2,
                "modelUsage": {"claude-fable-5-1": {}},
            },
        ]
        exe = self.fake(f"cat >/dev/null; printf '%s' '{json.dumps(payload)}'\n")
        result = runner.run_claude([exe], "prompt", cwd=self.tmp.name)
        self.assertTrue(result.ok)
        self.assertEqual(result.structured, {"verdict": "approve"})
        self.assertEqual(result.models, ["claude-fable-5-1"])
        self.assertEqual(result.num_turns, 2)

    def test_error_record(self) -> None:
        payload = {"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in"}
        exe = self.fake(f"cat >/dev/null; printf '%s' '{json.dumps(payload)}'\n")
        result = runner.run_claude([exe], "prompt", cwd=self.tmp.name)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "Not logged in")

    def test_no_json_at_all(self) -> None:
        exe = self.fake("cat >/dev/null; echo 'boom' >&2; exit 3\n")
        result = runner.run_claude([exe], "prompt", cwd=self.tmp.name)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "boom")
        self.assertEqual(result.returncode, 3)

    def test_prompt_arrives_on_stdin(self) -> None:
        exe = self.fake("P=$(cat); printf '{\"type\":\"result\",\"is_error\":false,\"result\":\"%s\"}' \"$P\"\n")
        result = runner.run_claude([exe], "hello there", cwd=self.tmp.name)
        self.assertEqual(result.text, "hello there")

    def test_timeout(self) -> None:
        exe = self.fake("sleep 5\n")
        result = runner.run_claude([exe], "prompt", cwd=self.tmp.name, timeout=0.2)
        self.assertFalse(result.ok)
        self.assertIn("did not finish", result.error)


if __name__ == "__main__":
    unittest.main()
