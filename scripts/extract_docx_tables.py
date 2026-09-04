#!/usr/bin/env python3
"""Extract table candidates from a DOCX attachment without normalizing values."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P


NUMBER_RE = re.compile(r"(?<![\w.])[+\-−]?\d+(?:[,.]\d+)*(?:[eE][+\-]?\d+)?(?![\w.])")
NON_DATA_RE = re.compile(
    r"table\s+of\s+contents|abbreviations?|author\s+contributions?|"
    r"reporting\s+checklist|search\s+strategy|questionnaire|eligibility\s+criteria|"
    r"submission\s+form",
    re.IGNORECASE,
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def iter_blocks(document: Document):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def assess(caption: str, rows: list[list[str]]) -> tuple[bool, str, int]:
    columns = max((len(row) for row in rows), default=0)
    numeric_cells = sum(bool(NUMBER_RE.search(cell)) for row in rows for cell in row)
    header = " ".join(rows[0]) if rows else ""
    if NON_DATA_RE.search(f"{caption} {header}"):
        return False, "likely_non_data_table", numeric_cells
    if len(rows) < 2 or columns < 2:
        return False, "insufficient_grid", numeric_cells
    if numeric_cells < 2:
        return False, "insufficient_numeric_data", numeric_cells
    return True, "numeric_tabular_candidate", numeric_cells


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", help="DOCX attachment path")
    parser.add_argument("--output", required=True, help="Candidate JSON output path")
    parser.add_argument("--role", default="attachment", choices=["main", "attachment"])
    args = parser.parse_args()

    source_path = pathlib.Path(args.docx).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    document = Document(source_path)
    candidates: list[dict[str, Any]] = []
    last_nonempty = ""
    last_table_caption = ""

    for block in iter_blocks(document):
        if isinstance(block, Paragraph):
            text = clean(block.text)
            if text:
                last_nonempty = text
                if re.search(r"\btable\s+s?\d+", text, re.IGNORECASE):
                    last_table_caption = text
            continue

        rows = [[clean(cell.text) for cell in row.cells] for row in block.rows]
        caption = last_table_caption or last_nonempty
        likely, reason, numeric_cells = assess(caption, rows)
        sequence = len(candidates) + 1
        match = re.search(r"\btable\s+(s?\d+[a-z]?)", caption, re.IGNORECASE)
        table_label = f"Table {match.group(1)}" if match else f"DOCX table {sequence}"
        candidates.append(
            {
                "candidate_id": f"{args.role}_docx_t{sequence:03d}",
                "source_role": args.role,
                "source_file": source_path.name,
                "source_sha256": sha256_file(source_path),
                "source_locator": f"DOCX table {sequence}",
                "table_label": table_label,
                "caption": caption,
                "rows": rows,
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
                "numeric_cell_count": numeric_cells,
                "likely_data_table": likely,
                "assessment": reason,
            }
        )
        last_table_caption = ""

    payload = {
        "schema_version": "1.0",
        "extractor": "python-docx",
        "source_role": args.role,
        "source_file": source_path.name,
        "source_sha256": sha256_file(source_path),
        "candidate_count": len(candidates),
        "likely_data_table_count": sum(item["likely_data_table"] for item in candidates),
        "candidates": candidates,
    }
    output_path = pathlib.Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "candidate_count": len(candidates)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
