#!/usr/bin/env python3
"""Package exactly the XLSX files listed in a conversion manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import zipfile


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="conversion_manifest.json from export_pure_data.mjs")
    parser.add_argument("--output", required=True, help="Destination ZIP path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest_path = pathlib.Path(args.manifest).expanduser().resolve()
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("workbooks")
    if not isinstance(items, list) or not items:
        raise RuntimeError("Manifest contains no workbooks")

    files: list[pathlib.Path] = []
    seen_names: set[str] = set()
    for item in items:
        filename = pathlib.Path(str(item.get("filename", ""))).name
        if not filename.lower().endswith(".xlsx"):
            raise RuntimeError(f"Non-XLSX manifest entry: {filename}")
        if filename.lower() in seen_names:
            raise RuntimeError(f"Duplicate workbook filename: {filename}")
        seen_names.add(filename.lower())
        file_path = (root / filename).resolve()
        if file_path.parent != root or not file_path.is_file():
            raise RuntimeError(f"Missing or unsafe workbook path: {filename}")
        if item.get("sha256") and sha256_file(file_path) != item["sha256"]:
            raise RuntimeError(f"Workbook hash mismatch: {filename}")
        files.append(file_path)

    output_path = pathlib.Path(args.output).expanduser().resolve()
    if output_path.exists() and not args.force:
        raise FileExistsError(f"Refusing to overwrite existing ZIP: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w"
    with zipfile.ZipFile(output_path, mode, compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in files:
            archive.write(file_path, arcname=file_path.name)

    with zipfile.ZipFile(output_path) as archive:
        entries = archive.namelist()
        if entries != [file_path.name for file_path in files]:
            raise RuntimeError("ZIP entry list does not match the conversion manifest")
        if any(not entry.lower().endswith(".xlsx") for entry in entries):
            raise RuntimeError("ZIP contains a non-XLSX entry")

    result = {
        "zip": str(output_path),
        "sha256": sha256_file(output_path),
        "entry_count": len(files),
        "entries": [file_path.name for file_path in files],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
