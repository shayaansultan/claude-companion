"""Render Claude's results as markdown for Codex to relay verbatim."""

from __future__ import annotations

from typing import Any

from .runner import ClaudeResult

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _footer(result: ClaudeResult) -> list[str]:
    bits = []
    if result.models:
        bits.append(", ".join(result.models))
    if result.num_turns is not None:
        bits.append(f"{result.num_turns} turn(s)")
    if result.duration_ms is not None:
        bits.append(f"{result.duration_ms / 1000:.1f}s")
    if result.cost_usd is not None:
        bits.append(f"${result.cost_usd:.4f}")
    return ["", f"_Claude Code · {' · '.join(bits)}_"] if bits else []


def _line_range(finding: dict) -> str:
    start = finding.get("line_start")
    end = finding.get("line_end")
    if not isinstance(start, int) or start < 1:
        return ""
    if not isinstance(end, int) or end <= start:
        return f":{start}"
    return f":{start}-{end}"


def _normalize_finding(raw: Any, index: int) -> dict:
    src = raw if isinstance(raw, dict) else {}

    def text(key: str, default: str) -> str:
        value = src.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else default

    return {
        "severity": text("severity", "low").lower(),
        "title": text("title", f"Finding {index + 1}"),
        "body": text("body", "No details provided."),
        "file": text("file", "unknown"),
        "line_start": src.get("line_start"),
        "line_end": src.get("line_end"),
        "confidence": src.get("confidence"),
        "recommendation": text("recommendation", ""),
    }


def render_review(result: ClaudeResult, *, target_label: str, summary: str) -> str:
    lines = ["# Claude Review", "", f"Target: {target_label}", f"Scope: {summary}"]

    if not result.ok:
        lines += ["", "Claude review failed.", "", f"- Error: {result.error}"]
        if result.stderr and result.stderr != result.error:
            lines += ["", "stderr:", "", "```text", result.stderr, "```"]
        return "\n".join(lines).rstrip() + "\n"

    data = result.structured
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        lines += ["", "Claude did not return structured review output. Raw final message:", "", "```text", result.text or "(empty)", "```"]
        lines += _footer(result)
        return "\n".join(lines).rstrip() + "\n"

    findings = [_normalize_finding(f, i) for i, f in enumerate(data["findings"])]
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 4))
    verdict = str(data.get("verdict") or "unknown").strip()
    lines += [f"Verdict: {verdict}", "", str(data.get("summary") or "").strip(), ""]

    if not findings:
        lines.append("No material findings.")
    else:
        lines.append("Findings:")
        for f in findings:
            conf = f["confidence"]
            conf_text = f", confidence {conf:.2f}" if isinstance(conf, (int, float)) else ""
            lines.append(f"- [{f['severity']}] {f['title']} ({f['file']}{_line_range(f)}{conf_text})")
            lines.append(f"  {f['body']}")
            if f["recommendation"]:
                lines.append(f"  Recommendation: {f['recommendation']}")

    steps = [s.strip() for s in data.get("next_steps") or [] if isinstance(s, str) and s.strip()]
    if steps:
        lines += ["", "Next steps:"] + [f"- {s}" for s in steps]

    lines += _footer(result)
    return "\n".join(lines).rstrip() + "\n"


def render_task(result: ClaudeResult, *, mode_label: str) -> str:
    lines = ["# Claude Task", "", f"Mode: {mode_label}", ""]
    if not result.ok:
        lines += ["Claude task failed.", "", f"- Error: {result.error}"]
        if result.stderr and result.stderr != result.error:
            lines += ["", "stderr:", "", "```text", result.stderr, "```"]
        return "\n".join(lines).rstrip() + "\n"
    lines.append(result.text.strip() or "Claude finished without a final message.")
    lines += _footer(result)
    return "\n".join(lines).rstrip() + "\n"
