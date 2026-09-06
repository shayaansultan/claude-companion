"""claude-companion: review code or delegate a task to Claude Code.

    claude-companion review [--base REF] [--scope auto|working-tree|branch] [--focus TEXT]
    claude-companion task [--write] "<request>"
    claude-companion setup
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .doctor import render_report, run_checks
from .git import SCOPES, GitError, collect_context, resolve_target
from .render import render_review, render_task
from .runner import EFFORTS, PERMISSION_MODES, ClaudeUnavailable, build_argv, progress, run_claude

ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = ROOT / "prompts"
SCHEMAS = ROOT / "schemas"

EDIT_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit"]


def _template(name: str, variables: dict[str, str]) -> str:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _dry_run(argv: list[str], prompt: str, *, cwd: str) -> int:
    print(f"# cwd: {cwd}")
    print("# argv:")
    for part in argv:
        print(f"#   {part if len(part) < 120 else part[:117] + '...'}")
    print("# prompt:")
    print(prompt)
    return 0


def _add_common(parser: argparse.ArgumentParser, *, default_model: str | None, default_effort: str) -> None:
    parser.add_argument(
        "--model",
        default=default_model,
        help=f"Claude model alias or full name (default: {default_model or 'your Claude Code default'})",
    )
    parser.add_argument("--effort", choices=EFFORTS, default=default_effort, help=f"Reasoning effort (default: {default_effort})")
    parser.add_argument("--max-turns", type=int, help="Cap the number of agentic turns")
    parser.add_argument("--max-budget-usd", type=float, help="Stop when API spend exceeds this amount")
    parser.add_argument("--timeout", type=float, help="Seconds to wait for Claude before giving up")
    parser.add_argument("--cwd", default=os.getcwd(), help="Repository directory (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Print the raw result as JSON instead of markdown")
    parser.add_argument("--dry-run", action="store_true", help="Print the claude command and prompt without running it")


def cmd_review(args: argparse.Namespace) -> int:
    try:
        target = resolve_target(args.cwd, scope=args.scope, base=args.base)
        context = collect_context(args.cwd, target, inline=None if args.inline is None else args.inline)
    except GitError as exc:
        print(f"claude-companion: {exc}", file=sys.stderr)
        return 1

    if context.file_count == 0 and target.mode == "working-tree":
        print("claude-companion: nothing to review, the working tree is clean.", file=sys.stderr)
        return 1

    schema = json.loads((SCHEMAS / "review-output.schema.json").read_text(encoding="utf-8"))
    # Claude's validator rejects "$schema" (no resolver for the draft URL).
    schema = {k: v for k, v in schema.items() if not k.startswith("$")}
    prompt = _template(
        "review",
        {
            "TARGET_LABEL": target.label,
            "USER_FOCUS": args.focus.strip() if args.focus else "None. Review the whole change.",
            "COLLECTION_GUIDANCE": context.collection_guidance,
            "REPO_ROOT": context.repo_root,
            "REVIEW_INPUT": context.content,
        },
    )

    try:
        argv = build_argv(
            permission_mode="plan",
            model=args.model,
            effort=args.effort,
            json_schema=schema,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget_usd,
            disallowed_tools=EDIT_TOOLS,
        )
    except ClaudeUnavailable as exc:
        print(f"claude-companion: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        return _dry_run(argv, prompt, cwd=context.repo_root)

    progress(
        f"reviewing {target.label} ({context.file_count} file(s), "
        f"{'inline diff' if context.inline_diff else 'self-collect'}) with Claude Code..."
    )
    result = run_claude(argv, prompt, cwd=context.repo_root, timeout=args.timeout)

    if args.json:
        print(json.dumps({"target": target.__dict__, "summary": context.summary, **result.__dict__}, indent=2, default=str))
    else:
        sys.stdout.write(render_review(result, target_label=target.label, summary=context.summary))
    return 0 if result.ok else 1


def cmd_task(args: argparse.Namespace) -> int:
    request = " ".join(args.request).strip()
    if not request or request == "-":
        request = sys.stdin.read().strip()
    if not request:
        print("claude-companion: no task given. Pass the request as arguments or on stdin.", file=sys.stderr)
        return 2

    if args.permission_mode:
        mode = args.permission_mode
    else:
        mode = "acceptEdits" if args.write else "plan"
    writable = mode != "plan"
    mode_label = f"{'write' if writable else 'read-only'} ({mode})"

    prompt = _template(
        "task",
        {
            "MODE_INSTRUCTIONS": (
                "You may edit files in this repository. Make the change, verify it as far as your tools allow, "
                "and report exactly which files you touched."
                if writable
                else "You are read-only. Do not attempt to edit files; investigate and report."
            ),
            "CWD": os.path.abspath(args.cwd),
            "REQUEST": request,
        },
    )

    try:
        argv = build_argv(
            permission_mode=mode,
            model=args.model,
            effort=args.effort,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget_usd,
            disallowed_tools=None if writable else EDIT_TOOLS,
        )
    except ClaudeUnavailable as exc:
        print(f"claude-companion: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        return _dry_run(argv, prompt, cwd=os.path.abspath(args.cwd))

    progress(f"delegating task to Claude Code in {mode_label} mode...")
    result = run_claude(argv, prompt, cwd=os.path.abspath(args.cwd), timeout=args.timeout)

    if args.json:
        print(json.dumps({"mode": mode, **result.__dict__}, indent=2, default=str))
    else:
        sys.stdout.write(render_task(result, mode_label=mode_label))
    return 0 if result.ok else 1


def cmd_setup(args: argparse.Namespace) -> int:
    report = run_checks()
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        sys.stdout.write(render_report(report))
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-companion", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"claude-companion {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="Read-only review of the working tree or a branch, with structured findings")
    review.add_argument("--base", help="Review commits since this ref (implies --scope branch)")
    review.add_argument("--scope", choices=SCOPES, default="auto", help="auto: working tree if dirty, else branch vs default")
    review.add_argument("--focus", help="Extra instructions or an area to weight heavily")
    inline = review.add_mutually_exclusive_group()
    inline.add_argument("--inline", dest="inline", action="store_true", default=None, help="Always inline the full diff")
    inline.add_argument("--self-collect", dest="inline", action="store_false", help="Never inline; Claude runs git itself")
    # Reviews always run on the latest Fable at high effort; a second opinion
    # is only worth having from the strongest reviewer available.
    _add_common(review, default_model="fable", default_effort="high")
    review.set_defaults(func=cmd_review)

    task = sub.add_parser("task", help="Delegate any request to Claude Code")
    task.add_argument("request", nargs="*", help="The request (or '-' / empty to read stdin)")
    task.add_argument("--write", action="store_true", help="Allow Claude to edit files (permission mode acceptEdits)")
    task.add_argument("--permission-mode", choices=PERMISSION_MODES, help="Override the permission mode entirely")
    # Tasks inherit the user's Claude Code default model, at high effort.
    _add_common(task, default_model=None, default_effort="high")
    task.set_defaults(func=cmd_task)

    setup = sub.add_parser("setup", help="Check that claude, auth, git and the Codex sandbox are ready")
    setup.add_argument("--json", action="store_true")
    setup.set_defaults(func=cmd_setup)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
