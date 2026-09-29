#!/usr/bin/env bash
#
# One-time setup for cc_agent: install lean4-skills plugin and lean-lsp MCP server
# for Claude Code. This script is idempotent — safe to run multiple times.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { echo -e "\033[0;36m[info]\033[0m  $*"; }
ok()    { echo -e "\033[0;32m[ok]\033[0m    $*"; }
warn()  { echo -e "\033[1;33m[warn]\033[0m  $*"; }
err()   { echo -e "\033[0;31m[error]\033[0m $*" >&2; }

# ============================================================
#  Step 1: Check prerequisites
# ============================================================
info "=== Step 1: Checking prerequisites ==="

if ! command -v claude &>/dev/null; then
    err "Claude Code CLI not found. Install it first:"
    err "  npm install -g @anthropic-ai/claude-code"
    exit 1
fi
ok "Claude Code CLI found: $(command -v claude)"

if ! command -v python3 &>/dev/null; then
    err "python3 not found."
    exit 1
fi
ok "python3 found"

if ! command -v uvx &>/dev/null; then
    warn "uvx not found. lean-lsp MCP server requires uvx (from uv)."
    warn "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# ============================================================
#  Step 2: Disable conflicting global/user Lean skills
# ============================================================
info "=== Step 2: Isolating project from global Lean configurations ==="

USER_SETTINGS="$HOME/.claude/settings.json"

if [[ -f "$USER_SETTINGS" ]]; then
    # 2a: Find and locally disable any global Lean plugins
    while IFS= read -r plugin_name; do
        [[ -z "$plugin_name" ]] && continue
        info "Disabling global plugin '${plugin_name}' for this project..."
        # Disabling at project scope adds it to the local disabledPlugins list
        claude plugin disable "$plugin_name" --scope project 2>/dev/null || true
    done < <(python3 -c "
import json
try:
    with open('$USER_SETTINGS') as f:
        data = json.load(f)
    for key in data.get('enabledPlugins', {}):
        if 'lean' in key.lower():
            print(key)
except: pass
" 2>/dev/null)

    # 2b: Find and locally mask any differently-named global Lean MCPs
    while IFS= read -r mcp_name; do
        [[ -z "$mcp_name" ]] && continue
        if [[ "$mcp_name" != "lean-lsp" ]]; then
            info "Removing any local overlaps for global MCP '${mcp_name}'..."
            claude mcp remove "$mcp_name" --scope project 2>/dev/null || true
        fi
    done < <(python3 -c "
import json
try:
    with open('$USER_SETTINGS') as f:
        data = json.load(f)
    for key in data.get('mcpServers', {}):
        if 'lean' in key.lower() and 'lsp' in key.lower():
            print(key)
except: pass
" 2>/dev/null)
    ok "Project isolated from global configurations"
else
    ok "No global Claude settings file found. Skipping isolation."
fi


# ============================================================
#  Step 3: Install lean4-skills plugin (project scope)
# ============================================================
info "=== Step 3: Installing lean4-skills plugin ==="

# 3a: Register cameronfreer/lean4-skills marketplace (idempotent)
if claude plugin marketplace list 2>/dev/null | grep -q "cameronfreer/lean4-skills"; then
    ok "cameronfreer/lean4-skills marketplace already registered"
else
    info "Adding cameronfreer/lean4-skills marketplace..."
    MARKET_OUTPUT=$(claude plugin marketplace add cameronfreer/lean4-skills 2>&1) || true
    if echo "$MARKET_OUTPUT" | grep -qi "success\|already\|added"; then
        ok "cameronfreer/lean4-skills marketplace registered"
    else
        warn "Marketplace registration output: $MARKET_OUTPUT"
        warn "Continuing anyway — plugin may already be available."
    fi
fi

# 3b: Install lean4@lean4-skills plugin (project scope)
# We skip checking if it exists because the install command is naturally idempotent.
info "Installing lean4@lean4-skills plugin (project scope)..."
INSTALL_OUTPUT=$(claude plugin install lean4@lean4-skills --scope project 2>&1) || true
if echo "$INSTALL_OUTPUT" | grep -qi "success\|installed\|already"; then
    ok "lean4@lean4-skills plugin active at project scope"
else
    err "Failed to install lean4 plugin: $INSTALL_OUTPUT"
    err "Try manually: claude plugin install lean4@lean4-skills --scope project"
    exit 1
fi

# ============================================================
#  Step 4: Add lean-lsp MCP server (project scope)
# ============================================================
info "=== Step 4: Adding lean-lsp MCP server ==="

info "Adding/Verifying lean-lsp MCP server (project scope)..."
# Run the command and capture both stdout and stderr
MCP_OUTPUT=$(claude mcp add --transport stdio --scope project lean-lsp -- uvx lean-lsp-mcp 2>&1) || true

# Check for the specific "already exists" message
if echo "$MCP_OUTPUT" | grep -qi "already exists in .mcp.json"; then
    ok "lean-lsp MCP server already exists (project scope)"

# Check for the specific "Added" message
elif echo "$MCP_OUTPUT" | grep -qi "Added stdio MCP server"; then
    ok "lean-lsp MCP server successfully added to project config"

# Fallback for unexpected errors or changes in Claude CLI output
else
    warn "Unexpected output when adding MCP server:"
    warn "$MCP_OUTPUT"
    warn "You may need to verify or add it manually:"
    warn "  claude mcp add --transport stdio --scope project lean-lsp -- uvx lean-lsp-mcp"
fi

# ============================================================
#  Step 5: Set up Python environment
# ============================================================
info "=== Step 5: Setting up Python environment ==="

cd "$SCRIPT_DIR"

if command -v uv &>/dev/null; then
    uv sync 2>&1 || { warn "uv sync failed — dependencies may need manual install"; }
    ok "Python dependencies installed via uv"
else
    warn "uv not found. Install dependencies manually:"
    warn "  pip install fire pyyaml"
fi

# ============================================================
#  Done
# ============================================================
echo ""
echo "========================================"
echo -e "\033[0;32m  cc_agent setup complete!\033[0m"
echo "========================================"
echo ""
echo "Usage:"
echo "  # Set up Lean projects dataset:"
echo "  python -m scripts.run_golf setup-project"
echo ""
echo "  # Run proof optimization (see README.md for more details and options):"
echo "  python -m scripts.run_golf run \\"
echo "    --project-root /path/to/lean-project \\" 
echo "    --output-dir results/golf_001 \\" 
echo "    --max-turns 40 \\" 
echo "    --parallel --max-workers 4"
echo ""
echo "  # Run with specific model and effort:"
echo "  python -m scripts.run_golf run \\"
echo "    --project-root /path/to/lean-project \\"
echo "    --model opus --effort max"
echo ""
echo "  # Override auto-discovery with explicit JSONL file:"
echo "  python -m scripts.run_golf run \\" 
echo "    --project-root /path/to/lean-project \\" 
echo "    --jsonl-file /custom/path/to/data.jsonl"
echo ""