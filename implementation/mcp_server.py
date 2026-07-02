"""FastMCP server exposing a SQLite database via search / insert / aggregate.

Run with stdio transport (default, for MCP clients):

    python mcp_server.py

Run with HTTP transport for demos:

    python mcp_server.py --transport http --port 8000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError
from pydantic import Field

from db import SQLiteAdapter, ValidationError
from init_db import DB_PATH, create_database

mcp = FastMCP("SQLite Lab MCP Server")

# Create the database on first run so the server works out of the box.
create_database(DB_PATH, force=False)
adapter = SQLiteAdapter(DB_PATH)


@mcp.tool(name="search")
def search(
    table: Annotated[str, Field(description="Table to query, e.g. 'students'")],
    filters: Annotated[
        list[dict[str, Any]] | None,
        Field(
            description=(
                "Optional list of filters, each an object "
                '{"column": str, "op": str, "value": any}. '
                "Supported ops: eq, ne, lt, lte, gt, gte, like, in."
            )
        ),
    ] = None,
    columns: Annotated[
        list[str] | None,
        Field(description="Columns to return; omit for all columns"),
    ] = None,
    limit: Annotated[int, Field(description="Max rows to return (1-100)")] = 20,
    offset: Annotated[int, Field(description="Rows to skip, for pagination")] = 0,
    order_by: Annotated[str | None, Field(description="Column to sort by")] = None,
    descending: Annotated[bool, Field(description="Sort descending")] = False,
) -> dict[str, Any]:
    """Search rows in a table with optional filters, ordering, and pagination."""
    try:
        return adapter.search(
            table,
            columns=columns,
            filters=filters,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending,
        )
    except ValidationError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(name="insert")
def insert(
    table: Annotated[str, Field(description="Table to insert into")],
    values: Annotated[
        dict[str, Any],
        Field(description="Column-to-value mapping for the new row"),
    ],
) -> dict[str, Any]:
    """Insert one row into a table and return the inserted row with its ID."""
    try:
        return adapter.insert(table, values)
    except ValidationError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(name="aggregate")
def aggregate(
    table: Annotated[str, Field(description="Table to aggregate over")],
    metric: Annotated[
        str,
        Field(description="Aggregate function: count, avg, sum, min, or max"),
    ],
    column: Annotated[
        str | None,
        Field(description="Column to aggregate; optional for count"),
    ] = None,
    filters: Annotated[
        list[dict[str, Any]] | None,
        Field(description="Optional filters, same shape as in the search tool"),
    ] = None,
    group_by: Annotated[
        str | None, Field(description="Optional column to group results by")
    ] = None,
) -> dict[str, Any]:
    """Compute count / avg / sum / min / max over a table, optionally grouped."""
    try:
        return adapter.aggregate(
            table, metric, column=column, filters=filters, group_by=group_by
        )
    except ValidationError as exc:
        raise ToolError(str(exc)) from exc


@mcp.resource(
    "schema://database",
    name="database_schema",
    description="Full schema of every table in the lab database, as JSON.",
    mime_type="application/json",
)
def database_schema() -> str:
    return json.dumps(adapter.get_database_schema(), indent=2)


@mcp.resource(
    "schema://table/{table_name}",
    name="table_schema",
    description="Schema of a single table, as JSON.",
    mime_type="application/json",
)
def table_schema(table_name: str) -> str:
    try:
        return json.dumps(adapter.get_table_schema(table_name), indent=2)
    except ValidationError as exc:
        raise ResourceError(str(exc)) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLite Lab MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport to run (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)
