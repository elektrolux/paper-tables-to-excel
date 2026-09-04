#!/usr/bin/env python3
"""Extract table candidates from a MinerU result directory.

This script preserves raw table evidence and applies only a conservative
candidate flag. Final inclusion and cell normalization require source review.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import pathlib
import re
from html.parser import HTMLParser
from typing import Any, Iterable


NUMBER_RE = re.compile(r"(?<![\w.])[+\-−]?\d+(?:[,.]\d+)*(?:[eE][+\-]?\d+)?(?![\w.])")
NON_DATA_RE = re.compile(
    r"table\s+of\s+contents|abbreviations?|author\s+contributions?|"
    r"reporting\s+checklist|search\s+strategy|questionnaire|eligibility\s+criteria|"
    r"inclusion\s+criteria|exclusion\s+criteria|submission\s+form",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(part for part in (clean_text(item) for item in value) if part)
    if isinstance(value, dict):
        return " ".join(part for part in (clean_text(item) for item in value.values()) if part)
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


class TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.table_depth = 0
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self.table_depth == 0:
                self.rows = []
            self.table_depth += 1
        elif self.table_depth and tag == "tr":
            self.row = []
        elif self.table_depth and tag in {"td", "th"}:
            self.cell = []
        elif self.table_depth and tag == "br" and self.cell is not None:
            self.cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self.table_depth and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.table_depth and tag in {"td", "th"} and self.cell is not None:
            if self.row is None:
                self.row = []
            self.row.append(clean_text("".join(self.cell)))
            self.cell = None
        elif self.table_depth and tag == "tr" and self.row is not None:
            if any(cell for cell in self.row):
                self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self.tables.append(self.rows)
                self.rows = []


def parse_markdown_table(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if "|" not in stripped:
            continue
        cells = [clean_text(cell) for cell in stripped.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def rows_from_body(body: Any) -> list[list[str]]:
    if isinstance(body, list):
        if body and all(isinstance(row, list) for row in body):
            return [[clean_text(cell) for cell in row] for row in body]
        return []
    if isinstance(body, dict):
        for key in ("rows", "cells", "data"):
            if key in body:
                rows = rows_from_body(body[key])
                if rows:
                    return rows
        return []
    if not isinstance(body, str):
        return []
    if "<table" in body.lower():
        parser = TableHTMLParser()
        parser.feed(body)
        if parser.tables:
            return parser.tables[0]
    rows = parse_markdown_table(body)
    if rows:
        return rows
    tab_rows = [
        [clean_text(cell) for cell in line.split("\t")]
        for line in body.splitlines()
        if "\t" in line
    ]
    return [row for row in tab_rows if len(row) >= 2]


def rectangular_shape(rows: list[list[str]]) -> tuple[int, int]:
    return len(rows), max((len(row) for row in rows), default=0)


def candidate_assessment(caption: str, rows: list[list[str]]) -> tuple[bool, str, int]:
    row_count, column_count = rectangular_shape(rows)
    numeric_cells = sum(bool(NUMBER_RE.search(cell)) for row in rows for cell in row)
    header_text = " ".join(rows[0]) if rows else ""
    if NON_DATA_RE.search(f"{caption} {header_text}"):
        return False, "likely_non_data_table", numeric_cells
    if row_count < 2 or column_count < 2:
        return False, "insufficient_grid", numeric_cells
    if numeric_cells < 2:
        return False, "insufficient_numeric_data", numeric_cells
    return True, "numeric_tabular_candidate", numeric_cells


def content_blocks(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, list):
        yield from (item for item in data if isinstance(item, dict))
        return
    if isinstance(data, dict):
        for key in ("content_list", "content", "blocks", "items"):
            value = data.get(key)
            if isinstance(value, list):
                yield from (item for item in value if isinstance(item, dict))
                return


def block_page(block: dict[str, Any]) -> int | None:
    for key in ("page_idx", "page_index"):
        value = block.get(key)
        if isinstance(value, int):
            return value + 1
    for key in ("page_no", "page_num", "page"):
        value = block.get(key)
        if isinstance(value, int):
            return value
    return None


def body_from_block(block: dict[str, Any]) -> Any:
    for key in ("table_body", "table_content", "html", "content", "text", "body"):
        value = block.get(key)
        if value not in (None, "", []):
            return value
    return ""


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_manifest(root: pathlib.Path) -> dict[str, Any]:
    manifest_path = root / "mineru_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"MinerU manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def add_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    *,
    role: str,
    source_file: str,
    source_sha256: str | None,
    page: int | None,
    caption: str,
    footnote: str,
    image_path: str | None,
    bbox: Any,
    raw_body: Any,
    rows: list[list[str]],
    origin: str,
) -> None:
    raw_text = raw_body if isinstance(raw_body, str) else json.dumps(raw_body, ensure_ascii=False)
    fingerprint = hashlib.sha256(raw_text.encode("utf-8", errors="replace")).hexdigest()
    if fingerprint in seen:
        return
    seen.add(fingerprint)
    likely, reason, numeric_cells = candidate_assessment(caption, rows)
    sequence = len(candidates) + 1
    page_part = f"p{page:03d}" if page is not None else "punknown"
    candidates.append(
        {
            "candidate_id": f"{role}_{page_part}_t{sequence:03d}",
            "source_role": role,
            "source_file": source_file,
            "source_sha256": source_sha256,
            "page": page,
            "caption": caption,
            "footnote": footnote,
            "image_path": image_path,
            "bbox": bbox,
            "origin": origin,
            "rows": rows,
            "raw_table_body": raw_body,
            "row_count": len(rows),
            "column_count": max((len(row) for row in rows), default=0),
            "numeric_cell_count": numeric_cells,
            "likely_data_table": likely,
            "assessment": reason,
            "raw_fingerprint_sha256": fingerprint.upper(),
        }
    )


def extract_from_markdown(
    markdown_path: pathlib.Path,
    candidates: list[dict[str, Any]],
    seen: set[str],
    role: str,
    source_file: str,
    source_sha256: str | None,
) -> None:
    text = markdown_path.read_text(encoding="utf-8", errors="replace")
    for match in re.finditer(r"<table\b.*?</table>", text, flags=re.IGNORECASE | re.DOTALL):
        body = match.group(0)
        preceding = [line.strip() for line in text[: match.start()].splitlines()[-4:] if line.strip()]
        add_candidate(
            candidates, seen, role=role, source_file=source_file,
            source_sha256=source_sha256, page=None,
            caption=clean_text(preceding[-1]) if preceding else "", footnote="",
            image_path=None, bbox=None, raw_body=body, rows=rows_from_body(body),
            origin=str(markdown_path.name),
        )

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if "|" not in lines[index]:
            index += 1
            continue
        start = index
        block: list[str] = []
        while index < len(lines) and "|" in lines[index]:
            block.append(lines[index])
            index += 1
        rows = parse_markdown_table("\n".join(block))
        if len(rows) >= 2:
            preceding = [line.strip() for line in lines[max(0, start - 4):start] if line.strip()]
            body = "\n".join(block)
            add_candidate(
                candidates, seen, role=role, source_file=source_file,
                source_sha256=source_sha256, page=None,
                caption=clean_text(preceding[-1]) if preceding else "", footnote="",
                image_path=None, bbox=None, raw_body=body, rows=rows,
                origin=str(markdown_path.name),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mineru_output", help="Directory created by mineru_convert.py")
    parser.add_argument("--output", required=True, help="Candidate JSON output path")
    parser.add_argument("--role", required=True, choices=["main", "attachment"])
    parser.add_argument("--source-file", help="Original PDF path for hash and identity")
    args = parser.parse_args()

    root = pathlib.Path(args.mineru_output).expanduser().resolve()
    manifest = load_manifest(root)
    source_path = pathlib.Path(args.source_file).expanduser().resolve() if args.source_file else None
    source_file = (
        source_path.name if source_path else
        str(manifest.get("source", {}).get("file_name") or manifest.get("source", {}).get("value") or "unknown.pdf")
    )
    source_sha256 = sha256_file(source_path) if source_path and source_path.is_file() else None
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    content_paths = sorted(root.rglob("*_content_list.json"))
    for content_path in content_paths:
        data = json.loads(content_path.read_text(encoding="utf-8"))
        for block in content_blocks(data):
            block_type = str(block.get("type") or block.get("block_type") or "").lower()
            if "table" not in block_type:
                continue
            raw_body = body_from_block(block)
            rows = rows_from_body(raw_body)
            image_path = block.get("img_path") or block.get("image_path")
            add_candidate(
                candidates, seen,
                role=args.role,
                source_file=source_file,
                source_sha256=source_sha256,
                page=block_page(block),
                caption=clean_text(block.get("table_caption") or block.get("caption") or block.get("title")),
                footnote=clean_text(block.get("table_footnote") or block.get("footnote")),
                image_path=str(image_path) if image_path else None,
                bbox=block.get("bbox"),
                raw_body=raw_body,
                rows=rows,
                origin=str(content_path.relative_to(root)),
            )

    for markdown_path in sorted(root.rglob("full.md")):
        extract_from_markdown(
            markdown_path, candidates, seen, args.role, source_file, source_sha256
        )

    payload = {
        "schema_version": "1.0",
        "extractor": "MinerU",
        "mineru_output": str(root),
        "source_role": args.role,
        "source_file": source_file,
        "source_sha256": source_sha256,
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
