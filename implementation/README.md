# SQLite Lab MCP Server

A [FastMCP](https://gofastmcp.com) server that exposes a small SQLite database
(students / courses / enrollments) through three MCP tools — `search`,
`insert`, `aggregate` — plus schema resources, with strict input validation.

## Project Structure

```text
implementation/
  db.py               # SQLiteAdapter: validation + safe SQL execution
  init_db.py          # reproducible schema + seed data (creates lab.db)
  mcp_server.py       # FastMCP server: tools, resources, transports
  verify_server.py    # repeatable end-to-end verification script
  tests/
    test_server.py    # pytest suite (adapter unit tests + MCP e2e tests)
  start_inspector.sh  # launch MCP Inspector (macOS/Linux)
  start_inspector.ps1 # launch MCP Inspector (Windows)
  requirements.txt
```

Database logic (`db.py`) is fully separated from server logic
(`mcp_server.py`). The adapter's public surface (`search` / `insert` /
`aggregate` / schema inspection) is database-agnostic, so a `PostgresAdapter`
with the same methods could be swapped in without touching the MCP layer.

## Setup

Requires Python 3.10+.

```bash
cd implementation
python -m pip install -r requirements.txt
python init_db.py          # creates/reset lab.db with seed data
```

## Run the Server

```bash
python mcp_server.py                              # stdio (default, for MCP clients)
python mcp_server.py --transport http --port 8000 # HTTP for demos
```

The server auto-creates `lab.db` on first run if it does not exist, so MCP
clients can spawn it directly. Run `python init_db.py` any time to reset the
data to a known state.

## Tools

### `search`

Search rows with optional filters, projection, ordering, and pagination.

| Parameter | Type | Description |
|---|---|---|
| `table` | str | Table to query (`students`, `courses`, `enrollments`) |
| `filters` | list | Objects `{"column", "op", "value"}`; ops: `eq ne lt lte gt gte like in` |
| `columns` | list | Columns to return (default: all) |
| `limit` / `offset` | int | Pagination; limit is capped at 100 |
| `order_by` / `descending` | str / bool | Sorting |

Example call:

```json
{"table": "students", "filters": [{"column": "cohort", "op": "eq", "value": "A1"}], "order_by": "score", "descending": true}
```

### `insert`

Insert one row and return the stored row including its generated ID.

```json
{"table": "students", "values": {"name": "Mai Do", "email": "mai.do@example.com", "cohort": "A1", "score": 8.0}}
```

### `aggregate`

Compute `count`, `avg`, `sum`, `min`, or `max`, with optional filters and
`group_by`. `count` works without a column; the other metrics require one.

```json
{"table": "students", "metric": "avg", "column": "score", "group_by": "cohort"}
```

## Resources

| URI | Content |
|---|---|
| `schema://database` | JSON schema of every table |
| `schema://table/{table_name}` | JSON schema of one table, e.g. `schema://table/students` |

## Safety and Validation

- Table and column names are validated against the **live database schema**
  before any SQL string is built; unknown identifiers are rejected with a
  message listing valid options.
- All user values are passed as **bound parameters** — never concatenated.
- Filter operators and aggregate metrics come from fixed allowlists.
- Empty inserts, bad pagination values, and constraint violations return
  clear `ToolError` messages instead of stack traces.

## Testing and Verification

```bash
# full pytest suite (27 tests: adapter units + MCP end-to-end)
python -m pytest tests/ -v

# repeatable verification checklist (discovery, valid calls, error calls)
python verify_server.py
```

`verify_server.py` connects through the in-memory FastMCP client and prints a
PASS/FAIL line for each rubric item: server startup, tool discovery, resource
discovery, valid `search`/`insert`/`aggregate` calls, and five rejected
invalid calls. Exit code is non-zero if any check fails.

## MCP Inspector

```bash
./start_inspector.sh        # macOS/Linux
./start_inspector.ps1       # Windows PowerShell
```

Or manually:

```bash
npx -y @modelcontextprotocol/inspector python /ABSOLUTE/PATH/TO/implementation/mcp_server.py
```

In the Inspector UI check: the three tools appear with schemas, both schema
resources appear, a valid `search` succeeds, and a `search` on a missing
table returns a clear error.

## Client Configuration

### Claude Code

A ready `.mcp.json` is included at the repository root. Generic shape:

```json
{
  "mcpServers": {
    "sqlite-lab": {
      "type": "stdio",
      "command": "python",
      "args": ["/ABSOLUTE/PATH/TO/implementation/mcp_server.py"]
    }
  }
}
```

Then inside Claude Code:

- `/mcp` — confirm `sqlite-lab` is connected and lists 3 tools + resources
- `@sqlite-lab:schema://database` — pull the schema resource into context
- Prompt: *"Use the sqlite-lab server to show the top 2 students by score."*

### Gemini CLI

```bash
gemini mcp add sqlite-lab /ABSOLUTE/PATH/TO/python /ABSOLUTE/PATH/TO/implementation/mcp_server.py --description "SQLite lab FastMCP server" --timeout 10000
gemini mcp list   # should show Connected
gemini --allowed-mcp-server-names sqlite-lab --yolo -p "Use the sqlite-lab MCP server and show me the top 2 students by score."
```

### Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.sqlite_lab]
command = "python"
args = ["/ABSOLUTE/PATH/TO/implementation/mcp_server.py"]
```

## Demo Script (~2 minutes)

1. `python init_db.py` — show reproducible seed data.
2. `python verify_server.py` — 15/15 checks pass on screen.
3. Open Inspector — show tools and resources, run one valid `search` and one
   failing call (`table: "no_such_table"`).
4. In Claude Code (or Gemini CLI): read `@sqlite-lab:schema://database`, ask
   for average score by cohort, insert a new student, search for it.
