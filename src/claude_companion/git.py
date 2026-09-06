"""Git scope detection and review-context collection.

Mirrors the target/context logic of openai/codex-plugin-cc (Apache-2.0) so a
review means the same thing in both directions: an explicit --base wins, then
an explicit --scope, then "working tree if dirty, else branch vs default".
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

MAX_UNTRACKED_BYTES = 24 * 1024
# Inline the full diff into the prompt only when it is small. Larger targets
# get a summary and Claude collects the diff itself with read-only git.
INLINE_MAX_FILES = 6
INLINE_MAX_BYTES = 160 * 1024

SCOPES = ("auto", "working-tree", "branch")


class GitError(RuntimeError):
    pass


def _git(cwd: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed. Install Git and retry.") from exc
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise GitError(f"git {' '.join(args)} failed: {detail}")
    return proc


def _lines(text: str) -> list[str]:
    return [line for line in text.strip().splitlines() if line]


def ensure_repository(cwd: str) -> str:
    proc = _git(cwd, ["rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0:
        raise GitError("This command must run inside a Git repository.")
    return proc.stdout.strip()


def current_branch(cwd: str) -> str:
    return _git(cwd, ["branch", "--show-current"]).stdout.strip() or "HEAD"


def detect_default_branch(cwd: str) -> str:
    symbolic = _git(cwd, ["symbolic-ref", "refs/remotes/origin/HEAD"], check=False)
    if symbolic.returncode == 0:
        head = symbolic.stdout.strip()
        prefix = "refs/remotes/origin/"
        if head.startswith(prefix):
            return head[len(prefix):]
    for candidate in ("main", "master", "trunk"):
        if _git(cwd, ["show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], check=False).returncode == 0:
            return candidate
        if _git(cwd, ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{candidate}"], check=False).returncode == 0:
            return f"origin/{candidate}"
    raise GitError(
        "Unable to detect the repository default branch. Pass --base <ref> or use --scope working-tree."
    )


@dataclass
class WorkingTreeState:
    staged: list[str] = field(default_factory=list)
    unstaged: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)

    @property
    def is_dirty(self) -> bool:
        return bool(self.staged or self.unstaged or self.untracked)

    @property
    def files(self) -> list[str]:
        return sorted(set(self.staged) | set(self.unstaged) | set(self.untracked))


def working_tree_state(cwd: str) -> WorkingTreeState:
    return WorkingTreeState(
        staged=_lines(_git(cwd, ["diff", "--cached", "--name-only"]).stdout),
        unstaged=_lines(_git(cwd, ["diff", "--name-only"]).stdout),
        untracked=_lines(_git(cwd, ["ls-files", "--others", "--exclude-standard"]).stdout),
    )


@dataclass
class ReviewTarget:
    mode: str  # "working-tree" | "branch"
    label: str
    base_ref: str | None = None
    explicit: bool = True


def resolve_target(cwd: str, *, scope: str = "auto", base: str | None = None) -> ReviewTarget:
    ensure_repository(cwd)
    if scope not in SCOPES:
        raise GitError(f'Unsupported review scope "{scope}". Use one of: {", ".join(SCOPES)}, or pass --base <ref>.')
    if base:
        return ReviewTarget("branch", f"branch diff against {base}", base_ref=base)
    if scope == "working-tree":
        return ReviewTarget("working-tree", "working tree diff")
    if scope == "branch":
        detected = detect_default_branch(cwd)
        return ReviewTarget("branch", f"branch diff against {detected}", base_ref=detected)
    if working_tree_state(cwd).is_dirty:
        return ReviewTarget("working-tree", "working tree diff", explicit=False)
    detected = detect_default_branch(cwd)
    return ReviewTarget("branch", f"branch diff against {detected}", base_ref=detected, explicit=False)


@dataclass
class ReviewContext:
    repo_root: str
    branch: str
    target: ReviewTarget
    summary: str
    content: str
    changed_files: list[str]
    inline_diff: bool

    @property
    def file_count(self) -> int:
        return len(self.changed_files)

    @property
    def collection_guidance(self) -> str:
        if self.inline_diff:
            return (
                "The repository context below contains the full diff. Treat it as primary evidence, "
                "and read surrounding code with your tools whenever a finding depends on it."
            )
        return (
            "The repository context below is a lightweight summary because the change is large. "
            "Collect the diff yourself with read-only git commands (see the Git Commands section) "
            "before finalizing findings."
        )


def _section(title: str, body: str) -> str:
    body = body.strip()
    return f"## {title}\n\n{body if body else '(none)'}\n"


def _is_probably_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _format_untracked(repo_root: str, rel: str) -> str:
    path = os.path.join(repo_root, rel)
    try:
        st = os.stat(path)
    except OSError:
        return f"### {rel}\n(skipped: broken symlink or unreadable file)"
    if os.path.isdir(path):
        return f"### {rel}\n(skipped: directory)"
    if st.st_size > MAX_UNTRACKED_BYTES:
        return f"### {rel}\n(skipped: {st.st_size} bytes exceeds {MAX_UNTRACKED_BYTES} byte limit)"
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return f"### {rel}\n(skipped: unreadable file)"
    if not _is_probably_text(data):
        return f"### {rel}\n(skipped: binary file)"
    return f"### {rel}\n```\n{data.decode('utf-8').rstrip()}\n```"


DIFF_FLAGS = ["--no-ext-diff", "--submodule=diff", "--no-color"]


def _measure(cwd: str, args: list[str]) -> int:
    return len(_git(cwd, args).stdout.encode("utf-8"))


def collect_context(cwd: str, target: ReviewTarget, *, inline: bool | None = None) -> ReviewContext:
    repo_root = ensure_repository(cwd)
    branch = current_branch(repo_root)

    if target.mode == "working-tree":
        state = working_tree_state(repo_root)
        files = state.files
        staged_args = ["diff", "--cached", *DIFF_FLAGS]
        unstaged_args = ["diff", *DIFF_FLAGS]
        diff_bytes = _measure(repo_root, staged_args) + _measure(repo_root, unstaged_args)
        inline_diff = inline if inline is not None else (len(files) <= INLINE_MAX_FILES and diff_bytes <= INLINE_MAX_BYTES)
        status = _git(repo_root, ["status", "--short", "--untracked-files=all"]).stdout
        untracked_body = "\n\n".join(_format_untracked(repo_root, f) for f in state.untracked)
        git_commands = (
            "git status --short --untracked-files=all\n"
            "git diff --cached\n"
            "git diff\n"
            "git ls-files --others --exclude-standard"
        )
        if inline_diff:
            parts = [
                _section("Git Status", status),
                _section("Staged Diff", _git(repo_root, staged_args).stdout),
                _section("Unstaged Diff", _git(repo_root, unstaged_args).stdout),
                _section("Untracked Files", untracked_body),
            ]
        else:
            parts = [
                _section("Git Status", status),
                _section("Staged Diff Stat", _git(repo_root, ["diff", "--shortstat", "--cached"]).stdout),
                _section("Unstaged Diff Stat", _git(repo_root, ["diff", "--shortstat"]).stdout),
                _section("Changed Files", "\n".join(files)),
                _section("Untracked Files", untracked_body),
                _section("Git Commands", git_commands),
            ]
        summary = (
            f"Reviewing {len(state.staged)} staged, {len(state.unstaged)} unstaged, "
            f"and {len(state.untracked)} untracked file(s)."
        )
        return ReviewContext(repo_root, branch, target, summary, "\n".join(parts), files, inline_diff)

    assert target.base_ref
    merge_base = _git(repo_root, ["merge-base", "HEAD", target.base_ref]).stdout.strip()
    commit_range = f"{merge_base}..HEAD"
    files = _lines(_git(repo_root, ["diff", "--name-only", commit_range]).stdout)
    diff_args = ["diff", *DIFF_FLAGS, commit_range]
    diff_bytes = _measure(repo_root, diff_args)
    inline_diff = inline if inline is not None else (len(files) <= INLINE_MAX_FILES and diff_bytes <= INLINE_MAX_BYTES)
    log = _git(repo_root, ["log", "--oneline", "--decorate", "--no-color", commit_range]).stdout
    stat = _git(repo_root, ["diff", "--stat", "--no-color", commit_range]).stdout
    parts = [_section("Commit Log", log), _section("Diff Stat", stat)]
    if inline_diff:
        parts.append(_section("Branch Diff", _git(repo_root, diff_args).stdout))
    else:
        parts.append(_section("Changed Files", "\n".join(files)))
        parts.append(_section("Git Commands", f"git diff {commit_range}\ngit log --oneline {commit_range}"))
    summary = f"Reviewing branch {branch} against {target.base_ref} from merge-base {merge_base[:12]}."
    return ReviewContext(repo_root, branch, target, summary, "\n".join(parts), files, inline_diff)
