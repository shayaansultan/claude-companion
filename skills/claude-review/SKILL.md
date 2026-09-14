---
name: claude-review
description: Get a second-opinion code review from Claude Code on the current working tree or branch. Use when the user asks for a review, a second pair of eyes, or to check changes before committing or opening a PR, or before finishing a substantial change of your own. Returns findings ranked by severity with file and line. Review only, never fixes.
---

# Claude Review

Runs Claude Code headlessly in read-only mode over the current git changes and
returns structured findings. You relay them; you do not act on them.

## Command

```
claude-companion review [--base <ref>] [--scope auto|working-tree|branch] [--focus "<text>"] [--model <m>] [--effort low|medium|high|xhigh|max]
```

`claude-companion` is on PATH after install. If it is not, run the copy next to
this skill: `<this skill's directory>/../../scripts/claude-companion`.

In OpenCode profiles, `CLAUDE_COMPANION_CONFIG_DIR` and
`CLAUDE_COMPANION_ACCOUNT` select and verify the Claude login. Keep that binding:
AnswerThis may use its own account while other profiles use Default. An account
mismatch stops dispatch; do not retry with another account. Run
`claude-companion setup --json` to inspect the effective binding. From an ordinary
terminal, `oc native <profile> claude review ...` supplies the same environment.

Scope resolution, in order: an explicit `--base` reviews commits since that ref;
`--scope working-tree` reviews staged, unstaged and untracked changes;
`--scope branch` diffs against the detected default branch; `auto` (the
default) picks working tree when it is dirty and branch otherwise. Pass
`--focus` only when the user names an area or concern to weight; do not add
instructions of your own.

## Model and effort

Defaults: `--model fable` (the latest Fable, the strongest reviewer) at
`--effort high`. Leave both alone for a normal review.

You may override them when there is a reason: the user names a model or
effort, or they ask for a quick or cheap pass (then `--model sonnet` or
`--model haiku` and `--effort medium` is reasonable). Aliases `fable`, `opus`,
`sonnet`, `haiku` and full model names are all accepted. Say which model ran
if you changed it; the report footer shows it too.

## Foreground or background

Size the change first: `git status --short` and `git diff --shortstat` (add
`--cached`, or use `<base>...HEAD` for a branch review). Untracked files count.

- One or two small files: run it in the foreground and wait.
- Anything larger, or unclear: run it in a **background terminal**, keep
  working or tell the user it is running, and poll for completion. A review
  typically takes between fifteen seconds and a few minutes; do not kill it
  early.

Progress lines go to stderr; the report is on stdout.

## Output rules

- Return the command's stdout **verbatim**. Do not paraphrase, summarise,
  reorder, or drop findings, and do not add commentary before or after it.
- Do not fix, patch, or offer to fix anything the review raises. If the user
  wants a finding addressed, that is a new request from them.
- A non-zero exit with an error on stderr means the review did not run. Show
  the error. If it says Claude is not installed, not logged in, or the sandbox
  has no network access, tell the user to run `claude-companion setup` in a
  terminal for the exact fix.
