#!/usr/bin/env bash
# Launch MCP Inspector against the lab server (macOS/Linux).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"

mkdir -p .npm-cache
NPM_CONFIG_CACHE="$PWD/.npm-cache" npx -y @modelcontextprotocol/inspector "$PYTHON_BIN" "$PWD/mcp_server.py"
