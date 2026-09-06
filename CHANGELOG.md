# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-06

### Added

- `$claude-review`: read-only review of the working tree or a branch with
  structured findings (severity, file, line range, confidence, recommendation).
- `$claude-task`: delegate any request to Claude Code, read-only by default,
  `--write` to allow edits.
- `claude-companion setup`: checks the Claude CLI, login state, git, and the
  Codex sandbox network setting.
- Self-hosted Codex marketplace at `.agents/plugins/marketplace.json`, so the
  repo installs with `codex plugin marketplace add shayaansultan/claude-companion`.
- `install.sh` for local development installs.
- Unit tests and CI across Python 3.11 to 3.13 on Linux and macOS.

[0.1.0]: https://github.com/shayaansultan/claude-companion/releases/tag/v0.1.0
