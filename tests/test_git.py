"""Scope resolution and context collection against a throwaway repository.

No Claude calls; these run anywhere git is installed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from claude_companion.git import GitError, collect_context, resolve_target, working_tree_state


def git(cwd: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


class TempRepo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        git(self.repo, "init", "-q", "-b", "main")
        self.write("a.py", "x = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, content: str) -> None:
        with open(os.path.join(self.repo, name), "w") as fh:
            fh.write(content)


class ResolveTargetTests(TempRepo):
    def test_not_a_repo(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(GitError):
                resolve_target(empty)

    def test_auto_picks_working_tree_when_dirty(self) -> None:
        self.write("a.py", "x = 2\n")
        target = resolve_target(self.repo)
        self.assertEqual(target.mode, "working-tree")
        self.assertFalse(target.explicit)

    def test_auto_picks_branch_when_clean(self) -> None:
        git(self.repo, "checkout", "-qb", "feat")
        self.write("b.py", "y = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "feat")
        target = resolve_target(self.repo)
        self.assertEqual(target.mode, "branch")
        self.assertEqual(target.base_ref, "main")

    def test_explicit_base_wins(self) -> None:
        self.write("a.py", "x = 2\n")
        target = resolve_target(self.repo, base="HEAD~0")
        self.assertEqual(target.mode, "branch")
        self.assertEqual(target.base_ref, "HEAD~0")

    def test_bad_scope(self) -> None:
        with self.assertRaises(GitError):
            resolve_target(self.repo, scope="everything")


class CollectContextTests(TempRepo):
    def test_working_tree_inlines_small_diff(self) -> None:
        self.write("a.py", "x = 2\n")
        self.write("new.txt", "hello\n")
        ctx = collect_context(self.repo, resolve_target(self.repo))
        self.assertTrue(ctx.inline_diff)
        self.assertEqual(ctx.changed_files, ["a.py", "new.txt"])
        self.assertIn("## Unstaged Diff", ctx.content)
        self.assertIn("-x = 1", ctx.content)
        self.assertIn("### new.txt", ctx.content)
        self.assertIn("hello", ctx.content)

    def test_working_tree_skips_binary_untracked(self) -> None:
        with open(os.path.join(self.repo, "blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01\x02")
        ctx = collect_context(self.repo, resolve_target(self.repo))
        self.assertIn("(skipped: binary file)", ctx.content)

    def test_self_collect_when_forced(self) -> None:
        self.write("a.py", "x = 2\n")
        ctx = collect_context(self.repo, resolve_target(self.repo), inline=False)
        self.assertFalse(ctx.inline_diff)
        self.assertIn("## Git Commands", ctx.content)
        self.assertNotIn("-x = 1", ctx.content)

    def test_branch_context(self) -> None:
        git(self.repo, "checkout", "-qb", "feat")
        self.write("a.py", "x = 3\n")
        git(self.repo, "commit", "-qam", "bump")
        ctx = collect_context(self.repo, resolve_target(self.repo, scope="branch"))
        self.assertEqual(ctx.target.base_ref, "main")
        self.assertIn("## Commit Log", ctx.content)
        self.assertIn("bump", ctx.content)
        self.assertIn("+x = 3", ctx.content)

    def test_clean_state(self) -> None:
        self.assertFalse(working_tree_state(self.repo).is_dirty)


if __name__ == "__main__":
    unittest.main()
