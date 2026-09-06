#!/bin/bash
# Register claude-companion with Codex.
#
# 1. Warms the uv venv (stdlib only, so this is instant).
# 2. Symlinks scripts/claude-companion onto PATH at ~/.local/bin.
# 3. Adds the plugin to the personal marketplace (~/.agents/plugins/marketplace.json).
# 4. Installs claude-companion@personal into Codex.
# 5. Runs `claude-companion setup` so you see what, if anything, is missing.
#
# Backs up every config it touches. Safe to re-run.

set -euo pipefail

PLUGIN_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SHIM="$PLUGIN_DIR/scripts/claude-companion"
MARKETPLACE="$HOME/.agents/plugins/marketplace.json"
BIN_DIR="$HOME/.local/bin"
STAMP=$(date +%Y%m%d-%H%M%S)

[ -x "$SHIM" ] || chmod +x "$SHIM"
echo "Plugin dir: $PLUGIN_DIR"
echo

command -v uv >/dev/null 2>&1 || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
uv sync --project "$PLUGIN_DIR" --quiet

# --- PATH -------------------------------------------------------------------
mkdir -p "$BIN_DIR"
ln -sfn "$SHIM" "$BIN_DIR/claude-companion"
echo "  PATH: $BIN_DIR/claude-companion -> $SHIM"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "  WARNING: $BIN_DIR is not on PATH; the skills fall back to the in-plugin script" ;;
esac

# --- Marketplace ------------------------------------------------------------
# The personal marketplace root is $HOME, so the plugin path is relative to it.
mkdir -p "$(dirname "$MARKETPLACE")"
[ -f "$MARKETPLACE" ] && cp "$MARKETPLACE" "$MARKETPLACE.bak-claude-companion-$STAMP"
MARKETPLACE="$MARKETPLACE" PLUGIN_DIR="$PLUGIN_DIR" uv run --project "$PLUGIN_DIR" --quiet python - <<'PY'
import json, os
path = os.environ["MARKETPLACE"]
plugin_dir = os.environ["PLUGIN_DIR"]
home = os.path.expanduser("~")
rel = "./" + os.path.relpath(plugin_dir, home) if plugin_dir.startswith(home + os.sep) else plugin_dir
try:
    with open(path) as fh:
        market = json.load(fh)
except FileNotFoundError:
    market = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
plugins = market.setdefault("plugins", [])
entry = {
    "name": "claude-companion",
    "source": {"source": "local", "path": rel},
    # Only ON_INSTALL / ON_USE are valid; anything else makes Codex drop the whole marketplace.
    "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
    "category": "Developer Tools",
}
for i, p in enumerate(plugins):
    if p.get("name") == "claude-companion":
        plugins[i] = entry
        break
else:
    plugins.append(entry)
with open(path, "w") as fh:
    json.dump(market, fh, indent=2)
    fh.write("\n")
print(f"  Marketplace: claude-companion -> {rel} ({len(plugins)} plugin(s) in {market.get('name')})")
PY

# --- Codex ------------------------------------------------------------------
if command -v codex >/dev/null 2>&1; then
  if codex plugin list 2>/dev/null | grep -q '^claude-companion@personal.*installed'; then
    echo "  Codex: plugin 'claude-companion@personal' already installed (remove and re-add to pick up changes)"
  else
    codex plugin add claude-companion@personal >/dev/null 2>&1 \
      && echo "  Codex: installed plugin 'claude-companion@personal'" \
      || echo "  Codex: plugin add failed; check 'codex plugin list' and $MARKETPLACE"
  fi
else
  echo "  Codex: 'codex' CLI not on PATH, skipped"
fi

echo
"$SHIM" setup || true
echo "Restart Codex to pick up the plugin."
