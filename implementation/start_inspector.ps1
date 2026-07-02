# Launch MCP Inspector against the lab server (Windows PowerShell).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python).Source
$server = Join-Path $here "mcp_server.py"

New-Item -ItemType Directory -Force (Join-Path $here ".npm-cache") | Out-Null
$env:NPM_CONFIG_CACHE = Join-Path $here ".npm-cache"

npx -y "@modelcontextprotocol/inspector" $python $server
