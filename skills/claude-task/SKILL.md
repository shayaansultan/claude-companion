---
name: claude-task
description: Delegate a task to Claude Code and return its report. Use when the user asks to hand something to Claude, wants a second implementation or diagnosis attempt, or when you are stuck and an independent pass would help. Read-only by default; add --write when the user wants Claude to make the change.
---

# Claude Task

Hands one request to Claude Code, running headlessly in this repository, and
returns its final report. You are a forwarder, not an orchestrator.

## Command

```
claude-companion task [--write] [--model <m>] [--effort low|medium|high|xhigh|max] [--max-turns N] "<request>"
```

`claude-companion` is on PATH after install. If it is not, run the copy next to
this skill: `<this skill's directory>/../../scripts/claude-companion`.

Long requests can go on stdin instead of as an argument.

## Choosing flags

- **Read-only is the default.** Claude can read, grep and run read-only
  commands but cannot edit. Use it for diagnosis, research, explanations, and
  "what would you change".
- **`--write`** lets Claude edit files in the working tree. Add it only when
  the user clearly wants Claude to make the change, not just describe it.
  Codex's own sandbox still applies to the run.
- **Model and effort.** Defaults: the user's Claude Code default model at
  `--effort high`. Override when the user names a model or effort, or when
  the task clearly warrants it: `--model fable` for a hard diagnosis or a
  large change, `--model sonnet` or `--model haiku` for a quick, cheap pass.
  Aliases `fable`, `opus`, `sonnet`, `haiku` and full model names are all
  accepted. Say which model ran if you changed it; the report footer shows it
  too.
- Strip routing words like "with Claude" or "in the background" from the
  request text; forward the task itself as the user phrased it.

## Foreground or background

A small, clearly bounded request: run in the foreground and wait. Anything
open-ended, multi-step, or likely to take more than a minute: run it in a
**background terminal**, keep working or tell the user it is running, and poll
for completion. Do not kill it early.

Progress lines go to stderr; the report is on stdout.

## Output rules

- Return the command's stdout **verbatim**, without commentary before or
  after it.
- After a `--write` run, the working tree has changed. Do not revert or redo
  Claude's edits; show `git status --short` if the user wants to see what
  moved.
- A non-zero exit with an error on stderr means the task did not run. Show the
  error. If it says Claude is not installed, not logged in, or the sandbox has
  no network access, tell the user to run `claude-companion setup` in a
  terminal for the exact fix.
