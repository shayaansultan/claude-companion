"""Rendering of structured review results and task results."""

from __future__ import annotations

import unittest

from claude_companion.render import render_review, render_task
from claude_companion.runner import ClaudeResult


def review(**overrides) -> ClaudeResult:
    base = dict(
        ok=True,
        text="",
        structured={
            "verdict": "needs-attention",
            "summary": "Do not ship.",
            "findings": [
                {
                    "severity": "low",
                    "title": "Nit",
                    "body": "Minor.",
                    "file": "a.py",
                    "line_start": 3,
                    "line_end": 3,
                    "confidence": 0.4,
                    "recommendation": "",
                },
                {
                    "severity": "critical",
                    "title": "Wrong operator",
                    "body": "add() subtracts.",
                    "file": "m.py",
                    "line_start": 1,
                    "line_end": 2,
                    "confidence": 0.98,
                    "recommendation": "Use +.",
                },
            ],
            "next_steps": ["Fix m.py"],
        },
        cost_usd=0.1234,
        duration_ms=12345,
        num_turns=4,
        models=["claude-fable-5-1"],
    )
    base.update(overrides)
    return ClaudeResult(**base)


class RenderReviewTests(unittest.TestCase):
    def test_sorts_by_severity_and_formats_lines(self) -> None:
        out = render_review(review(), target_label="working tree diff", summary="2 files")
        self.assertLess(out.index("[critical]"), out.index("[low]"))
        self.assertIn("(m.py:1-2, confidence 0.98)", out)
        self.assertIn("(a.py:3, confidence 0.40)", out)
        self.assertIn("Recommendation: Use +.", out)
        self.assertIn("Next steps:\n- Fix m.py", out)
        self.assertIn("claude-fable-5-1", out)
        self.assertIn("$0.1234", out)

    def test_no_findings(self) -> None:
        r = review()
        r.structured["findings"] = []
        r.structured["next_steps"] = []
        out = render_review(r, target_label="t", summary="s")
        self.assertIn("No material findings.", out)
        self.assertNotIn("Next steps", out)

    def test_error(self) -> None:
        out = render_review(ClaudeResult(ok=False, error="Not logged in"), target_label="t", summary="s")
        self.assertIn("Claude review failed.", out)
        self.assertIn("Not logged in", out)

    def test_unstructured_fallback(self) -> None:
        out = render_review(review(structured=None, text="free text"), target_label="t", summary="s")
        self.assertIn("did not return structured review output", out)
        self.assertIn("free text", out)


class RenderTaskTests(unittest.TestCase):
    def test_success(self) -> None:
        out = render_task(ClaudeResult(ok=True, text="Fixed it.", num_turns=2), mode_label="read-only (plan)")
        self.assertIn("Mode: read-only (plan)", out)
        self.assertIn("Fixed it.", out)
        self.assertIn("2 turn(s)", out)

    def test_failure(self) -> None:
        out = render_task(ClaudeResult(ok=False, error="boom"), mode_label="m")
        self.assertIn("Claude task failed.", out)
        self.assertIn("boom", out)


if __name__ == "__main__":
    unittest.main()
