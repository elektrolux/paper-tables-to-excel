#!/usr/bin/env python3
"""Validate normalized research tables before XLSX export."""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import re
import sys
from typing import Any


ALLOWED_TYPES = {"text", "integer", "number", "percent", "year", "boolean"}
FORBIDDEN_TEXT_SYMBOLS = re.compile(r"[%±()\[\]{}<>≤≥,;:–—*†‡]")
NUMBER_ATOM_RE = re.compile(r"[+\-−]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?")
P_VALUE_RE = re.compile(r"(^|\W)p(?:\s*[-_ ]?\s*value)?($|\W)", re.IGNORECASE)
SOURCE_RE = re.compile(r"\b(source|provenance|doi|url|web\s*link)\b", re.IGNORECASE)


def add(errors: list[dict[str, Any]], location: str, message: str, value: Any = None) -> None:
    item: dict[str, Any] = {"location": location, "message": message}
    if value is not None:
        item["value"] = value
    errors.append(item)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_column_name(name: str, location: str, errors: list[dict[str, Any]]) -> None:
    if not name.strip():
        add(errors, location, "Column name is empty")
        return
    if P_VALUE_RE.search(name):
        add(errors, location, "P value columns are forbidden", name)
    if SOURCE_RE.search(name):
        add(errors, location, "Source or provenance columns are forbidden", name)
    if FORBIDDEN_TEXT_SYMBOLS.search(name):
        add(errors, location, "Column name contains a forbidden symbol; use words instead", name)
    normalized = re.sub(r"[^a-z]+", " ", name.lower()).strip()
    if re.search(r"\bci\b", normalized) and not re.search(r"\b(lower|upper)\b", normalized):
        add(errors, location, "Confidence interval must be split into lower and upper columns", name)
    if "confidence interval" in normalized and not re.search(r"\b(lower|upper)\b", normalized):
        add(errors, location, "Confidence interval must be split into lower and upper columns", name)


def validate_text(value: Any, location: str, errors: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        add(errors, location, "Text column contains a non-text value", value)
        return
    if value.startswith("="):
        add(errors, location, "Formula-like text is forbidden", value)
    if "\n" in value or "\r" in value or "\t" in value:
        add(errors, location, "Text cell contains stacked or multiline values", value)
    if FORBIDDEN_TEXT_SYMBOLS.search(value):
        add(errors, location, "Text cell contains a forbidden symbol", value)
    atoms = NUMBER_ATOM_RE.findall(value)
    if len(atoms) > 1:
        add(errors, location, "Text cell contains multiple numeric atoms; split them into columns", value)


def validate_value(value: Any, column: dict[str, Any], location: str, errors: list[dict[str, Any]]) -> None:
    if value is None:
        return
    kind = column["type"]
    if kind == "text":
        validate_text(value, location, errors)
    elif kind in {"integer", "year"}:
        if not is_number(value) or int(value) != value:
            add(errors, location, f"{kind} column requires an integer or blank", value)
        elif kind == "year" and not 1000 <= int(value) <= 9999:
            add(errors, location, "Year must be a four-digit number", value)
    elif kind in {"number", "percent"}:
        if not is_number(value):
            add(errors, location, f"{kind} column requires a numeric value or blank", value)
    elif kind == "boolean" and not isinstance(value, bool):
        add(errors, location, "Boolean column requires true, false, or blank", value)


def canonical_rows(table: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    columns = tuple(str(column["name"]).casefold() for column in table.get("columns", []))
    rows = tuple(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in table.get("rows", []))
    return json.dumps(columns, ensure_ascii=False), rows


def duplicate_warnings(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for left_index, left in enumerate(tables):
        left_columns, left_rows = canonical_rows(left)
        for right_index in range(left_index + 1, len(tables)):
            right = tables[right_index]
            right_columns, right_rows = canonical_rows(right)
            if left_columns != right_columns:
                continue
            left_counts = collections.Counter(left_rows)
            right_counts = collections.Counter(right_rows)
            if left_counts == right_counts:
                relation = "exact_duplicate"
            elif not (left_counts - right_counts):
                relation = "left_subset_of_right"
            elif not (right_counts - left_counts):
                relation = "right_subset_of_left"
            else:
                continue
            warnings.append(
                {
                    "kind": relation,
                    "left_table_id": left.get("table_id"),
                    "right_table_id": right.get("table_id"),
                }
            )
    return warnings


def validate(payload: Any) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": [{"location": "$", "message": "Top level must be an object"}], "warnings": []}
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        add(errors, "$.tables", "At least one normalized table is required")
        tables = []

    seen_ids: set[str] = set()
    for table_index, table in enumerate(tables):
        base = f"$.tables[{table_index}]"
        if not isinstance(table, dict):
            add(errors, base, "Table must be an object")
            continue
        table_id = table.get("table_id")
        if not isinstance(table_id, str) or not table_id.strip():
            add(errors, f"{base}.table_id", "Non-empty table_id is required")
        elif table_id.casefold() in seen_ids:
            add(errors, f"{base}.table_id", "table_id must be unique", table_id)
        else:
            seen_ids.add(table_id.casefold())
        for field in ("title", "source_file", "source_sha256", "source_locator", "candidate_id"):
            if not isinstance(table.get(field), str) or not table[field].strip():
                add(errors, f"{base}.{field}", f"Non-empty {field} is required")
        if table.get("source_role") not in {"main", "attachment"}:
            add(errors, f"{base}.source_role", "source_role must be main or attachment", table.get("source_role"))

        columns = table.get("columns")
        rows = table.get("rows")
        if not isinstance(columns, list) or not columns:
            add(errors, f"{base}.columns", "At least one column is required")
            continue
        if not isinstance(rows, list) or not rows:
            add(errors, f"{base}.rows", "At least one data row is required")
            rows = []
        names: set[str] = set()
        for column_index, column in enumerate(columns):
            location = f"{base}.columns[{column_index}]"
            if not isinstance(column, dict):
                add(errors, location, "Column must be an object")
                continue
            name = column.get("name")
            kind = column.get("type")
            if not isinstance(name, str):
                add(errors, f"{location}.name", "Column name must be text", name)
            else:
                validate_column_name(name, f"{location}.name", errors)
                key = name.strip().casefold()
                if key in names:
                    add(errors, f"{location}.name", "Column names must be unique", name)
                names.add(key)
            if kind not in ALLOWED_TYPES:
                add(errors, f"{location}.type", "Unsupported column type", kind)
            precision = column.get("precision")
            if precision is not None and (not isinstance(precision, int) or not 0 <= precision <= 10):
                add(errors, f"{location}.precision", "Precision must be an integer from 0 through 10", precision)

        lower_names = {str(column.get("name", "")).lower() for column in columns if "confidence interval lower" in str(column.get("name", "")).lower()}
        upper_names = {str(column.get("name", "")).lower() for column in columns if "confidence interval upper" in str(column.get("name", "")).lower()}
        if bool(lower_names) != bool(upper_names):
            add(errors, f"{base}.columns", "Confidence interval lower and upper columns must both be present")

        for row_index, row in enumerate(rows):
            row_location = f"{base}.rows[{row_index}]"
            if not isinstance(row, list):
                add(errors, row_location, "Row must be an array")
                continue
            if len(row) != len(columns):
                add(errors, row_location, "Row width does not match column count", len(row))
                continue
            for column_index, value in enumerate(row):
                column = columns[column_index]
                if isinstance(column, dict) and column.get("type") in ALLOWED_TYPES:
                    validate_value(value, column, f"{row_location}[{column_index}]", errors)

    warnings = duplicate_warnings([table for table in tables if isinstance(table, dict)])
    return {
        "valid": not errors,
        "table_count": len(tables),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normalized_json")
    parser.add_argument("--report", help="Optional validation report JSON path")
    args = parser.parse_args()
    source = pathlib.Path(args.normalized_json).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    result = validate(payload)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        report = pathlib.Path(args.report).expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
