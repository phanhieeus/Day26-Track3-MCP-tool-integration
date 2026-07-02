"""Tests for the SQLite Lab MCP Server.

Two layers are covered:
- SQLiteAdapter unit tests against a temporary database
- end-to-end MCP tests through the in-memory FastMCP client

Run from the implementation/ directory:

    python -m pytest tests/ -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import SQLiteAdapter, ValidationError  # noqa: E402
from init_db import create_database  # noqa: E402


@pytest.fixture()
def adapter(tmp_path):
    db_path = create_database(tmp_path / "test.db")
    return SQLiteAdapter(db_path)


# ---------------------------------------------------------------------------
# Adapter: schema inspection
# ---------------------------------------------------------------------------


def test_list_tables(adapter):
    assert set(adapter.list_tables()) == {"students", "courses", "enrollments"}


def test_get_table_schema(adapter):
    schema = adapter.get_table_schema("students")
    names = [c["name"] for c in schema["columns"]]
    assert names == ["id", "name", "email", "cohort", "score"]
    assert schema["columns"][0]["primary_key"] is True


def test_get_database_schema(adapter):
    schema = adapter.get_database_schema()
    assert len(schema["tables"]) == 3


# ---------------------------------------------------------------------------
# Adapter: search
# ---------------------------------------------------------------------------


def test_search_all_rows(adapter):
    result = adapter.search("students")
    assert result["count"] == 6


def test_search_with_filter_and_order(adapter):
    result = adapter.search(
        "students",
        filters=[{"column": "cohort", "op": "eq", "value": "A1"}],
        order_by="score",
        descending=True,
    )
    scores = [r["score"] for r in result["rows"]]
    assert scores == sorted(scores, reverse=True)
    assert all(r["cohort"] == "A1" for r in result["rows"])


def test_search_pagination(adapter):
    page1 = adapter.search("students", limit=2, offset=0, order_by="id")
    page2 = adapter.search("students", limit=2, offset=2, order_by="id")
    assert page1["count"] == 2 and page2["count"] == 2
    assert page1["rows"][0]["id"] != page2["rows"][0]["id"]


def test_search_column_projection(adapter):
    result = adapter.search("students", columns=["name", "cohort"])
    assert set(result["rows"][0].keys()) == {"name", "cohort"}


def test_search_in_operator(adapter):
    result = adapter.search(
        "students", filters=[{"column": "cohort", "op": "in", "value": ["A1", "A2"]}]
    )
    assert result["count"] == 4


def test_search_limit_is_capped(adapter):
    result = adapter.search("students", limit=99999)
    assert result["limit"] == 100


def test_search_unknown_table(adapter):
    with pytest.raises(ValidationError, match="Unknown table"):
        adapter.search("no_such_table")


def test_search_unknown_column(adapter):
    with pytest.raises(ValidationError, match="Unknown column"):
        adapter.search("students", filters=[{"column": "nope", "op": "eq", "value": 1}])


def test_search_unsupported_operator(adapter):
    with pytest.raises(ValidationError, match="Unsupported operator"):
        adapter.search(
            "students", filters=[{"column": "score", "op": "regex", "value": ".*"}]
        )


def test_search_sql_injection_in_table_rejected(adapter):
    with pytest.raises(ValidationError, match="Unknown table"):
        adapter.search("students; DROP TABLE students; --")
    assert "students" in adapter.list_tables()


# ---------------------------------------------------------------------------
# Adapter: insert
# ---------------------------------------------------------------------------


def test_insert_returns_payload(adapter):
    result = adapter.insert(
        "students",
        {"name": "New Student", "email": "new@example.com", "cohort": "C1", "score": 7.5},
    )
    assert result["inserted_id"] is not None
    assert result["row"]["name"] == "New Student"
    assert adapter.search("students")["count"] == 7


def test_insert_empty_values(adapter):
    with pytest.raises(ValidationError, match="non-empty"):
        adapter.insert("students", {})


def test_insert_unknown_column(adapter):
    with pytest.raises(ValidationError, match="Unknown column"):
        adapter.insert("students", {"bogus": 1})


def test_insert_constraint_violation(adapter):
    with pytest.raises(ValidationError, match="constraint"):
        adapter.insert(
            "students",
            {"name": "Dup", "email": "an.nguyen@example.com", "cohort": "A1"},
        )


# ---------------------------------------------------------------------------
# Adapter: aggregate
# ---------------------------------------------------------------------------


def test_aggregate_count(adapter):
    result = adapter.aggregate("students", "count")
    assert result["results"][0]["value"] == 6


def test_aggregate_avg_group_by(adapter):
    result = adapter.aggregate("students", "avg", column="score", group_by="cohort")
    groups = {r["cohort"]: r["value"] for r in result["results"]}
    assert set(groups) == {"A1", "A2", "B1"}
    assert groups["A1"] == pytest.approx((8.5 + 7.2) / 2)


def test_aggregate_with_filter(adapter):
    result = adapter.aggregate(
        "students",
        "max",
        column="score",
        filters=[{"column": "cohort", "op": "eq", "value": "A2"}],
    )
    assert result["results"][0]["value"] == 9.1


def test_aggregate_bad_metric(adapter):
    with pytest.raises(ValidationError, match="Unsupported metric"):
        adapter.aggregate("students", "median", column="score")


def test_aggregate_missing_column(adapter):
    with pytest.raises(ValidationError, match="requires a column"):
        adapter.aggregate("students", "avg")


# ---------------------------------------------------------------------------
# End-to-end via the MCP client
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mcp_server():
    from mcp_server import mcp

    return mcp


def run(coro):
    return asyncio.run(coro)


def test_mcp_tool_discovery(mcp_server):
    from fastmcp import Client

    async def _run():
        async with Client(mcp_server) as client:
            return {t.name for t in await client.list_tools()}

    assert {"search", "insert", "aggregate"} <= run(_run())


def test_mcp_resource_discovery(mcp_server):
    from fastmcp import Client

    async def _run():
        async with Client(mcp_server) as client:
            resources = {str(r.uri) for r in await client.list_resources()}
            templates = {
                str(t.uriTemplate) for t in await client.list_resource_templates()
            }
            return resources, templates

    resources, templates = run(_run())
    assert "schema://database" in resources
    assert "schema://table/{table_name}" in templates


def test_mcp_search_call(mcp_server):
    from fastmcp import Client

    async def _run():
        async with Client(mcp_server) as client:
            res = await client.call_tool(
                "search",
                {"table": "students", "filters": [
                    {"column": "cohort", "op": "eq", "value": "A1"}
                ]},
            )
            return res.data

    data = run(_run())
    assert data["count"] >= 2


def test_mcp_invalid_call_returns_error(mcp_server):
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    async def _run():
        async with Client(mcp_server) as client:
            with pytest.raises(ToolError, match="Unknown table"):
                await client.call_tool("search", {"table": "no_such_table"})

    run(_run())


def test_mcp_read_table_schema_resource(mcp_server):
    import json

    from fastmcp import Client

    async def _run():
        async with Client(mcp_server) as client:
            contents = await client.read_resource("schema://table/students")
            return json.loads(contents[0].text)

    data = run(_run())
    assert data["table"] == "students"
