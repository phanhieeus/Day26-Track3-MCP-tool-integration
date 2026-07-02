"""Repeatable verification script for the SQLite Lab MCP Server.

Connects to the server in-memory via the FastMCP client and checks:

1. the server starts
2. the three tools are discoverable
3. the schema resources are discoverable
4. valid tool calls return useful results
5. invalid tool calls return clear errors

Run:

    python verify_server.py
"""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_server import mcp

PASS = "[PASS]"
FAIL = "[FAIL]"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append((ok, label))
    suffix = f" - {detail}" if detail else ""
    print(f"{PASS if ok else FAIL} {label}{suffix}")


async def expect_tool_error(client: Client, label: str, tool: str, args: dict) -> None:
    try:
        await client.call_tool(tool, args)
    except ToolError as exc:
        check(True, label, str(exc))
    else:
        check(False, label, "expected an error but the call succeeded")


async def main() -> None:
    async with Client(mcp) as client:
        check(True, "server starts and client connects")

        # --- discovery -------------------------------------------------
        tools = {t.name for t in await client.list_tools()}
        check(
            {"search", "insert", "aggregate"} <= tools,
            "tools discoverable (search, insert, aggregate)",
            f"found: {sorted(tools)}",
        )

        resources = {str(r.uri) for r in await client.list_resources()}
        templates = {str(t.uriTemplate) for t in await client.list_resource_templates()}
        check("schema://database" in resources, "schema://database resource listed")
        check(
            "schema://table/{table_name}" in templates,
            "schema://table/{table_name} template listed",
        )

        # --- resources -------------------------------------------------
        full = json.loads((await client.read_resource("schema://database"))[0].text)
        table_names = [t["table"] for t in full["tables"]]
        check(
            {"students", "courses", "enrollments"} <= set(table_names),
            "full schema resource readable",
            f"tables: {table_names}",
        )

        one = json.loads(
            (await client.read_resource("schema://table/students"))[0].text
        )
        check(
            one["table"] == "students" and any(c["name"] == "cohort" for c in one["columns"]),
            "per-table schema resource readable",
        )

        # --- valid tool calls -------------------------------------------
        res = await client.call_tool(
            "search",
            {
                "table": "students",
                "filters": [{"column": "cohort", "op": "eq", "value": "A1"}],
                "order_by": "score",
                "descending": True,
            },
        )
        rows = res.data["rows"]
        check(
            len(rows) >= 2 and all(r["cohort"] == "A1" for r in rows),
            "search: students in cohort A1 with ordering",
            f"{len(rows)} rows",
        )

        res = await client.call_tool(
            "insert",
            {
                "table": "students",
                "values": {
                    "name": "Verify Bot",
                    "email": f"verify-{asyncio.get_event_loop().time():.0f}@example.com",
                    "cohort": "Z9",
                    "score": 5.0,
                },
            },
        )
        check(
            res.data["inserted_id"] is not None
            and res.data["row"]["name"] == "Verify Bot",
            "insert: returns inserted payload with ID",
            f"id={res.data['inserted_id']}",
        )

        res = await client.call_tool("aggregate", {"table": "students", "metric": "count"})
        check(
            res.data["results"][0]["value"] >= 6,
            "aggregate: count rows",
            f"count={res.data['results'][0]['value']}",
        )

        res = await client.call_tool(
            "aggregate",
            {
                "table": "students",
                "metric": "avg",
                "column": "score",
                "group_by": "cohort",
            },
        )
        check(
            len(res.data["results"]) >= 3,
            "aggregate: average score grouped by cohort",
            f"{len(res.data['results'])} groups",
        )

        # --- invalid tool calls ------------------------------------------
        await expect_tool_error(
            client, "error: unknown table rejected", "search", {"table": "no_such_table"}
        )
        await expect_tool_error(
            client,
            "error: unknown column rejected",
            "search",
            {
                "table": "students",
                "filters": [{"column": "nope", "op": "eq", "value": 1}],
            },
        )
        await expect_tool_error(
            client,
            "error: unsupported operator rejected",
            "search",
            {
                "table": "students",
                "filters": [{"column": "score", "op": "regex", "value": ".*"}],
            },
        )
        await expect_tool_error(
            client,
            "error: bad aggregate metric rejected",
            "aggregate",
            {"table": "students", "metric": "median", "column": "score"},
        )
        await expect_tool_error(
            client, "error: empty insert rejected", "insert", {"table": "students", "values": {}}
        )

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
