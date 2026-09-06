<h1 align="center">Claude Companion</h1>

<p align="center">
  <strong>Get a second opinion from Claude Code without leaving Codex.</strong><br>
  A Codex plugin that hands code review and tasks to Claude Code, and brings the answer back.
</p>

<p align="center">
  <a href="https://github.com/shayaansultan/claude-companion/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/shayaansultan/claude-companion/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white">
  <img alt="Codex plugin" src="https://img.shields.io/badge/Codex-plugin-000000.svg">
  <img alt="Zero dependencies" src="https://img.shields.io/badge/dependencies-none-success.svg">
</p>

OpenAI ships [codex-plugin-cc](https://github.com/openai/codex-plugin-cc) so Claude Code users can call Codex.
Claude Companion is the other direction: two Codex skills that run the Claude Code CLI headlessly and
return its output verbatim.

| Skill | What it does |
| --- | --- |
| `$claude-review` | Read-only review of your working tree or branch. Findings ranked by severity, with file and line. Never edits. |
| `$claude-task` | Delegate any request to Claude. Read-only by default; `--write` lets it edit the working tree. |

## Quick start

```bash
codex plugin marketplace add shayaansultan/claude-companion
codex plugin add claude-companion@shayaansultan
```

Then, in `~/.codex/config.toml`, let the workspace-write sandbox reach the network. Codex runs the
plugin inside that sandbox and Claude needs to reach its API from there:

```toml
[sandbox_workspace_write]
network_access = true
```

Restart Codex and ask it to review your changes, or type `$claude-review`.

**Requirements:** [Claude Code](https://docs.claude.com/en/docs/claude-code) logged in (`claude auth login`),
[Codex CLI](https://developers.openai.com/codex) with plugins, Git, and Python 3.11+ on PATH.
No Python packages are needed.

## What you get

A real branch review of a two-file change with a planted bug, as Codex relays it (one finding
trimmed for length):

```
# Claude Review

Target: branch diff against main
Scope: Reviewing branch feat against main from merge-base 076e96d97aa2.
Verdict: needs-attention

No-ship. The new test_add asserts add(1, 2) == 3, but add still returns a - b, so the only test in the change fails immediately (confirmed: add(1, 2) returns -1). The diff reformatted add without fixing the operator, and the new div function ships with no test at all.

Findings:
- [high] add() still subtracts; new test_add fails against shipped code (m.py:1-2, confidence 0.98)
  m.py line 2 keeps `return a - b` while the new test_m.py asserts `add(1, 2) == 3`. Running the module confirms add(1, 2) returns -1, so the test suite introduced by this change is red on the commit that introduces it. The diff only touched whitespace in add, leaving the pre-existing operator bug in place. Either the implementation or the test is wrong; the function name and test intent indicate the implementation is.
  Recommendation: Change `return a - b` to `return a + b` in add(), then run pytest to confirm test_add passes.
- [medium] New div() has no test and undefined behavior on b == 0 is unspecified (m.py:5-6, confidence 0.85)
  test_m.py imports and tests only add. The div function added in this commit has zero coverage.
  div(1, 0) raises ZeroDivisionError (confirmed by running it); if that is the intended contract it
  should be pinned by a test.
  Recommendation: Add tests for div covering a normal case, a non-integer result, and the zero divisor case.

Next steps:
- Fix add() to return a + b and run pytest to verify test_add passes.
- Add test coverage for div(), including the b == 0 case, before merging.

_Claude Code · claude-fable-5-1 · 4 turn(s) · 39.9s · $0.8117_
```

## Usage

Inside Codex, just ask. "Get Claude to review this", "ask Claude why this test flakes", or
"have Claude add a dry-run flag" all route to the right skill. You can also invoke them
directly:

```
$claude-review
$claude-review --base origin/main
$claude-review --focus "the retry logic in sync.py"
$claude-task why does test_sync flake under load?
$claude-task --write add a --dry-run flag to the sync command
```

Codex runs small reviews in the foreground and larger ones in a background terminal, so a long
review never blocks the conversation.

### From a terminal

The same CLI works on its own. Run `install.sh` once to put `claude-companion` on your PATH, or call
`scripts/claude-companion` directly.

```bash
claude-companion review                     # working tree if dirty, else branch vs default
claude-companion review --base origin/main  # commits since a ref
claude-companion review --scope branch      # force branch mode
claude-companion task "explain the caching layer"
claude-companion task --write "fix the failing test in test_sync.py"
claude-companion setup                      # check claude, auth, git and sandbox config
claude-companion review --dry-run           # print the prompt and command without running
```

### Models and effort

| Command | Default model | Default effort |
| --- | --- | --- |
| `review` | `fable` (the latest Claude Fable) | `high` |
| `task` | your Claude Code default | `high` |

Override per run with `--model` and `--effort`. Aliases `fable`, `opus`, `sonnet`, `haiku` and full
model names are accepted. Codex will pick a different model when you ask for one or want a quick pass.
The footer of every report shows what actually ran.

## How it works

```
Codex  ──$claude-review──▶  claude-companion  ──claude -p──▶  Claude Code
  ▲                          resolves scope,                   plan mode, JSON schema,
  └────── markdown ◀──────── renders findings ◀── JSON ────── no MCP, no session files
```

- **Scope resolution** matches OpenAI's plugin: an explicit `--base` wins, then `--scope`, then
  working tree if dirty and branch against the default branch otherwise.
- **Small diffs are inlined** into the prompt. Large ones get a summary and Claude collects the diff
  itself with read-only git commands.
- **Reviews are read-only by construction.** Claude runs in plan mode with edit tools disallowed,
  and a JSON schema is enforced so the output is always structured.
- **Runs are hermetic.** No user MCP servers are loaded and no session files are written.
- **Shell, not MCP.** Codex blocks the turn on MCP tool calls and times them out at 60 seconds.
  A shell command can run in Codex's background terminal and be polled, so long reviews are fine.

## FAQ

**Claude says "Not logged in" only when run from Codex.**
The workspace-write sandbox has no network by default. Add the `network_access = true` line from
the quick start and restart Codex. `claude-companion setup` checks for it.

**Can I use a cheaper model for reviews?**
Yes: `$claude-review --model sonnet --effort medium`, or change the default in
`src/claude_companion/cli.py` if you run from a clone.

**Does Codex act on the findings?**
No. Both skills tell Codex to return Claude's output verbatim and not fix anything. Ask for a fix
separately if you want one.

**Does it work outside Codex?**
Yes. The CLI is plain Python with no dependencies. `install.sh` symlinks it onto your PATH.

**Why not `--bare`?**
Claude Code's bare mode skips the keychain read and reports "Not logged in".

## Development

```bash
git clone https://github.com/shayaansultan/claude-companion
cd claude-companion
./install.sh                                      # symlink, register in your personal marketplace, install
PYTHONPATH=src python3 -m unittest discover -s tests   # unit tests, no Claude calls
claude-companion review --dry-run                 # print the prompt and command, free
```

After editing skills or the launcher, refresh Codex's cached copy with
`codex plugin remove claude-companion@personal && codex plugin add claude-companion@personal`.
Keep the runtime stdlib-only: Codex runs the launcher inside its sandbox, where `uv` cannot write
its cache, so the plain-Python path must always work.

Layout:

```
.codex-plugin/plugin.json         manifest (skills only)
.agents/plugins/marketplace.json  makes this repo its own Codex marketplace
skills/claude-review              $claude-review
skills/claude-task                $claude-task
scripts/claude-companion          launcher (venv, else python3, else uv)
src/claude_companion/             cli, runner, git, render, doctor
prompts/                          review and task prompt templates
schemas/                          review output schema
tests/                            unit tests
```

Changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## License

MIT. The review output schema and scope-resolution logic are derived from
[openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) (Apache-2.0); see [NOTICE](NOTICE).
