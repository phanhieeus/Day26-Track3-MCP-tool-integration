"""Database layer for the SQLite Lab MCP Server.

All identifier validation happens here, before any SQL string is built.
User-supplied *values* are always passed as bound parameters; user-supplied
*identifiers* (table/column names) are only accepted if they exist in the
live database schema, so no raw input is ever concatenated into SQL.

The adapter is deliberately database-agnostic in its public surface
(search / insert / aggregate / schema inspection) so a PostgresAdapter
with the same methods could be swapped in later.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# Filter operators the MCP tools accept, mapped to their SQL form.
ALLOWED_OPERATORS: dict[str, str] = {
    "eq": "=",
    "ne": "!=",
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
    "like": "LIKE",
    "in": "IN",
}

ALLOWED_METRICS = {"count", "avg", "sum", "min", "max"}

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


class ValidationError(Exception):
    """Raised when a request cannot be safely executed."""


class SQLiteAdapter:
    """Thin, safety-first wrapper around a SQLite database file."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    # ------------------------------------------------------------------
    # Connection & schema inspection
    # ------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def list_tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        return [row["name"] for row in rows]

    def get_table_schema(self, table: str) -> dict[str, Any]:
        table = self._validate_table(table)
        with self.connect() as conn:
            rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return {
            "table": table,
            "columns": [
                {
                    "name": row["name"],
                    "type": row["type"],
                    "nullable": not row["notnull"],
                    "primary_key": bool(row["pk"]),
                    "default": row["dflt_value"],
                }
                for row in rows
            ],
        }

    def get_database_schema(self) -> dict[str, Any]:
        return {
            "database": self.db_path,
            "tables": [self.get_table_schema(t) for t in self.list_tables()],
        }

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_table(self, table: Any) -> str:
        if not isinstance(table, str) or not table:
            raise ValidationError("Table name must be a non-empty string.")
        tables = self.list_tables()
        if table not in tables:
            raise ValidationError(
                f"Unknown table '{table}'. Available tables: {', '.join(tables)}."
            )
        return table

    def _table_columns(self, table: str) -> list[str]:
        return [col["name"] for col in self.get_table_schema(table)["columns"]]

    def _validate_columns(self, table: str, columns: list[str]) -> list[str]:
        known = self._table_columns(table)
        for col in columns:
            if col not in known:
                raise ValidationError(
                    f"Unknown column '{col}' in table '{table}'. "
                    f"Available columns: {', '.join(known)}."
                )
        return columns

    def _build_where(
        self, table: str, filters: list[dict[str, Any]] | None
    ) -> tuple[str, list[Any]]:
        """Translate a list of {column, op, value} filters into SQL + params."""
        if not filters:
            return "", []

        clauses: list[str] = []
        params: list[Any] = []
        for i, f in enumerate(filters):
            if not isinstance(f, dict):
                raise ValidationError(
                    f"Filter #{i} must be an object like "
                    '{"column": ..., "op": ..., "value": ...}.'
                )
            missing = {"column", "op", "value"} - f.keys()
            if missing:
                raise ValidationError(
                    f"Filter #{i} is missing keys: {', '.join(sorted(missing))}."
                )
            column, op, value = f["column"], f["op"], f["value"]
            self._validate_columns(table, [column])
            if op not in ALLOWED_OPERATORS:
                raise ValidationError(
                    f"Unsupported operator '{op}'. "
                    f"Allowed operators: {', '.join(sorted(ALLOWED_OPERATORS))}."
                )
            if op == "in":
                if not isinstance(value, (list, tuple)) or not value:
                    raise ValidationError(
                        "Operator 'in' requires a non-empty list value."
                    )
                placeholders = ", ".join("?" for _ in value)
                clauses.append(f'"{column}" IN ({placeholders})')
                params.extend(value)
            else:
                clauses.append(f'"{column}" {ALLOWED_OPERATORS[op]} ?')
                params.append(value)

        return " WHERE " + " AND ".join(clauses), params

    # ------------------------------------------------------------------
    # Tool operations
    # ------------------------------------------------------------------

    def search(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
    ) -> dict[str, Any]:
        table = self._validate_table(table)

        if columns:
            self._validate_columns(table, columns)
            select_clause = ", ".join(f'"{c}"' for c in columns)
        else:
            select_clause = "*"

        where_sql, params = self._build_where(table, filters)

        order_sql = ""
        if order_by is not None:
            self._validate_columns(table, [order_by])
            order_sql = f' ORDER BY "{order_by}" {"DESC" if descending else "ASC"}'

        if not isinstance(limit, int) or limit < 1:
            raise ValidationError("limit must be a positive integer.")
        if not isinstance(offset, int) or offset < 0:
            raise ValidationError("offset must be a non-negative integer.")
        limit = min(limit, MAX_LIMIT)

        sql = (
            f'SELECT {select_clause} FROM "{table}"'
            f"{where_sql}{order_sql} LIMIT ? OFFSET ?"
        )
        with self.connect() as conn:
            rows = conn.execute(sql, [*params, limit, offset]).fetchall()

        return {
            "table": table,
            "count": len(rows),
            "limit": limit,
            "offset": offset,
            "rows": [dict(row) for row in rows],
        }

    def insert(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        table = self._validate_table(table)
        if not isinstance(values, dict) or not values:
            raise ValidationError(
                "values must be a non-empty object mapping columns to values."
            )
        columns = list(values.keys())
        self._validate_columns(table, columns)

        col_sql = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})'

        with self.connect() as conn:
            try:
                cursor = conn.execute(sql, list(values.values()))
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValidationError(f"Insert violates a constraint: {exc}") from exc
            row = conn.execute(
                f'SELECT * FROM "{table}" WHERE rowid = ?', [cursor.lastrowid]
            ).fetchone()

        return {
            "table": table,
            "inserted_id": cursor.lastrowid,
            "row": dict(row) if row else dict(values),
        }

    def aggregate(
        self,
        table: str,
        metric: str,
        column: str | None = None,
        filters: list[dict[str, Any]] | None = None,
        group_by: str | None = None,
    ) -> dict[str, Any]:
        table = self._validate_table(table)

        if not isinstance(metric, str) or metric.lower() not in ALLOWED_METRICS:
            raise ValidationError(
                f"Unsupported metric '{metric}'. "
                f"Allowed metrics: {', '.join(sorted(ALLOWED_METRICS))}."
            )
        metric = metric.lower()

        if metric == "count" and column is None:
            metric_sql = "COUNT(*)"
        else:
            if column is None:
                raise ValidationError(f"Metric '{metric}' requires a column.")
            self._validate_columns(table, [column])
            metric_sql = f'{metric.upper()}("{column}")'

        where_sql, params = self._build_where(table, filters)

        if group_by is not None:
            self._validate_columns(table, [group_by])
            sql = (
                f'SELECT "{group_by}", {metric_sql} AS value FROM "{table}"'
                f'{where_sql} GROUP BY "{group_by}" ORDER BY "{group_by}"'
            )
        else:
            sql = f'SELECT {metric_sql} AS value FROM "{table}"{where_sql}'

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return {
            "table": table,
            "metric": metric,
            "column": column,
            "group_by": group_by,
            "results": [dict(row) for row in rows],
        }
