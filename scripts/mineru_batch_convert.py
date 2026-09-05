#!/usr/bin/env python3
"""Convert multiple PDFs with one MinerU token from private stdin or a masked prompt."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

from mineru_convert import convert_input, read_token, validate_input


def safe_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return name[:80] or fallback


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Local PDF paths or public PDF URLs")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--token-stdin", action="store_true", help="Read a user-supplied token from a private stdin pipe instead of prompting.")
    parser.add_argument("--model-version", default="vlm", choices=["pipeline", "vlm", "MinerU-HTML"])
    parser.add_argument("--language", default="ch")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--disable-formula", action="store_true")
    parser.add_argument("--page-ranges")
    parser.add_argument("--data-id")
    parser.add_argument("--extra-format", action="append", choices=["docx", "html", "latex"])
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    for input_value in args.inputs:
        validate_input(input_value)

    try:
        token = read_token(args.token_stdin)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    root = pathlib.Path(args.output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        for index, input_value in enumerate(args.inputs, start=1):
            stem = pathlib.Path(input_value).stem if "://" not in input_value else f"remote_{index}"
            output_dir = root / f"{index:02d}_{safe_name(stem, f'pdf_{index}')}"
            results.append(convert_input(input_value, output_dir, token, args))
    finally:
        del token
    print(json.dumps({"converted": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
