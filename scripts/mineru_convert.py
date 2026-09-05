#!/usr/bin/env python3
"""Convert a paper file or URL with MinerU and unpack the result zip.

Accept a user-supplied MinerU token through private stdin or a masked prompt.
The token stays in process memory and is never printed, persisted, or accepted
as a command-line argument value.
"""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import http.client
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from ctypes import wintypes

API_BASE = "https://mineru.net"
POLL_STATES = {"pending", "running", "converting", "waiting-file"}
DONE_STATE = "done"
FAILED_STATE = "failed"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Refused redirect of authenticated MinerU request.")


def _prompt_token_windows() -> str:
    class CredUIInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hwndParent", wintypes.HWND),
            ("pszMessageText", wintypes.LPCWSTR),
            ("pszCaptionText", wintypes.LPCWSTR),
            ("hbmBanner", wintypes.HANDLE),
        ]

    ui = CredUIInfo()
    ui.cbSize = ctypes.sizeof(ui)
    ui.pszCaptionText = "MinerU API token"
    ui.pszMessageText = (
        "Enter your own MinerU API token for this conversion. "
        "The token is hidden, kept only in process memory, and is not saved."
    )
    user = ctypes.create_unicode_buffer("MinerU", 514)
    password = ctypes.create_unicode_buffer(2048)
    save = wintypes.BOOL(False)
    dll = ctypes.WinDLL("credui", use_last_error=True)
    prompt = dll.CredUIPromptForCredentialsW
    prompt.argtypes = [
        ctypes.POINTER(CredUIInfo), wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, wintypes.LPWSTR, wintypes.ULONG,
        wintypes.LPWSTR, wintypes.ULONG, ctypes.POINTER(wintypes.BOOL),
        wintypes.DWORD,
    ]
    prompt.restype = wintypes.DWORD
    flags = 0x40000 | 0x80 | 0x2 | 0x100000
    try:
        result = prompt(
            ctypes.byref(ui), "Codex/paper-tables-to-excel/MinerU-session",
            None, 0, user, len(user), password, len(password),
            ctypes.byref(save), flags,
        )
        if result == 1223:
            raise RuntimeError("MinerU token entry was cancelled.")
        if result:
            raise RuntimeError(f"MinerU token dialog failed with error {result}.")
        return password.value.strip()
    finally:
        ctypes.memset(password, 0, ctypes.sizeof(password))


def validate_token(token: str) -> str:
    token = token.strip()
    if not token:
        raise RuntimeError("A MinerU API token is required.")
    if token.lower().startswith("bearer ") or any(char.isspace() for char in token):
        raise RuntimeError("Enter only the token, without a Bearer prefix or whitespace.")
    return token


def prompt_token() -> str:
    token = (
        _prompt_token_windows()
        if os.name == "nt"
        else getpass.getpass(
            "Enter your MinerU API token (hidden and used only for this run): "
        ).strip()
    )
    return validate_token(token)


def read_token(token_stdin: bool = False) -> str:
    if not token_stdin:
        return prompt_token()
    if sys.stdin.isatty():
        raise RuntimeError("--token-stdin requires a private pipe, not an interactive terminal.")
    return validate_token(sys.stdin.readline())


def request_json(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = None
    headers = {
        "Accept": "*/*",
        "Authorization": f"Bearer {token}",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Do not echo server bodies: an upstream proxy may reflect Authorization.
        raise RuntimeError(f"MinerU HTTP {exc.code}; response body omitted for credential safety.") from None
    result = json.loads(body)
    if result.get("code") != 0:
        code = str(result.get('code')).replace(token, '[REDACTED]')
        msg = str(result.get('msg')).replace(token, '[REDACTED]')
        raise RuntimeError(f"MinerU API error {code}: {msg}")
    return result


def put_file(upload_url: str, file_path: pathlib.Path) -> None:
    # urllib auto-adds "Content-Type: application/x-www-form-urlencoded" for
    # requests with a body, which breaks OSS signed URLs from MinerU. Use
    # http.client directly so the signed request has no Content-Type header.
    parsed = urllib.parse.urlparse(upload_url)
    body = file_path.read_bytes()
    path = urllib.parse.urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_cls(parsed.netloc, timeout=300)
    try:
        connection.putrequest("PUT", path)
        connection.putheader("Host", parsed.netloc)
        connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        status = response.status
        response.read()
    finally:
        connection.close()
    if status < 200 or status >= 300:
        raise RuntimeError(f"Upload failed with HTTP {status}; response body omitted.")


def download_file(url: str, target: pathlib.Path, attempts: int = 4) -> None:
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                with target.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            return
                        handle.write(chunk)
        except Exception as exc:  # network downloads can occasionally drop after state=done
            last_error = exc
            if target.exists():
                target.unlink()
            if attempt < attempts:
                time.sleep(5 * attempt)
    error_kind = type(last_error).__name__ if last_error is not None else "unknown_error"
    raise RuntimeError(f"Download failed after {attempts} attempts ({error_kind}); URL omitted.") from last_error


def is_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"}


def validate_input(input_value: str) -> None:
    if is_url(input_value):
        return
    file_path = pathlib.Path(input_value).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if file_path.suffix.lower() != ".pdf":
        raise ValueError(f"MinerU input must be a PDF for this skill: {file_path.name}")


def common_payload(args: argparse.Namespace) -> dict:
    payload = {
        "model_version": args.model_version,
        "enable_table": True,
        "enable_formula": not args.disable_formula,
        "language": args.language,
    }
    if args.extra_format:
        payload["extra_formats"] = args.extra_format
    return payload


def submit_url(input_url: str, token: str, args: argparse.Namespace) -> str:
    payload = common_payload(args)
    payload["url"] = input_url
    payload["is_ocr"] = args.ocr
    if args.page_ranges:
        payload["page_ranges"] = args.page_ranges
    result = request_json("POST", f"{API_BASE}/api/v4/extract/task", token, payload)
    return result["data"]["task_id"]


def submit_local(file_path: pathlib.Path, token: str, args: argparse.Namespace) -> str:
    payload = common_payload(args)
    file_item = {
        "name": file_path.name,
        "data_id": args.data_id or file_path.stem,
        "is_ocr": args.ocr,
    }
    if args.page_ranges:
        file_item["page_ranges"] = args.page_ranges
    payload["files"] = [file_item]
    result = request_json("POST", f"{API_BASE}/api/v4/file-urls/batch", token, payload)
    batch_id = result["data"]["batch_id"]
    upload_urls = result["data"]["file_urls"]
    if not upload_urls:
        raise RuntimeError("MinerU returned no upload URL")
    put_file(upload_urls[0], file_path)
    return batch_id


def poll_url_task(task_id: str, token: str, args: argparse.Namespace) -> dict:
    url = f"{API_BASE}/api/v4/extract/task/{task_id}"
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        result = request_json("GET", url, token)
        data = result["data"]
        state = data.get("state")
        print_progress(state, data)
        if state == DONE_STATE:
            return data
        if state == FAILED_STATE:
            raise RuntimeError(f"MinerU task failed: {data.get('err_msg')}")
        if state not in POLL_STATES:
            raise RuntimeError(f"Unexpected MinerU state: {state}")
        time.sleep(args.interval)
    raise TimeoutError(f"Timed out waiting for task {task_id}")


def poll_batch(batch_id: str, token: str, args: argparse.Namespace) -> dict:
    url = f"{API_BASE}/api/v4/extract-results/batch/{batch_id}"
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        result = request_json("GET", url, token)
        items = result["data"].get("extract_result", [])
        if not items:
            time.sleep(args.interval)
            continue
        item = items[0]
        state = item.get("state")
        print_progress(state, item)
        if state == DONE_STATE:
            return item
        if state == FAILED_STATE:
            raise RuntimeError(f"MinerU task failed: {item.get('err_msg')}")
        if state not in POLL_STATES:
            raise RuntimeError(f"Unexpected MinerU state: {state}")
        time.sleep(args.interval)
    raise TimeoutError(f"Timed out waiting for batch {batch_id}")


def print_progress(state: str | None, data: dict) -> None:
    progress = data.get("extract_progress") or {}
    if progress:
        extracted = progress.get("extracted_pages")
        total = progress.get("total_pages")
        print(f"state={state} pages={extracted}/{total}", flush=True)
    else:
        print(f"state={state}", flush=True)


def unpack_zip(zip_path: pathlib.Path, output_dir: pathlib.Path) -> list[str]:
    extracted = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = output_dir / member.filename
            resolved = target.resolve()
            try:
                resolved.relative_to(output_dir.resolve())
            except ValueError:
                raise RuntimeError(f"Unsafe zip path: {member.filename}")
            zf.extract(member, output_dir)
            extracted.append(member.filename)
    return extracted


def write_manifest(output_dir: pathlib.Path, manifest: dict) -> None:
    (output_dir / "mineru_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_submission(output_dir: pathlib.Path, submission: dict) -> None:
    (output_dir / "mineru_submission.json").write_text(
        json.dumps(submission, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a paper with MinerU and unpack outputs.")
    parser.add_argument("input", help="Local PDF path or a public PDF URL.")
    parser.add_argument("--output", required=True, help="Output working directory.")
    parser.add_argument("--token-stdin", action="store_true", help="Read a user-supplied token from a private stdin pipe instead of prompting.")
    parser.add_argument("--model-version", default="vlm", choices=["pipeline", "vlm", "MinerU-HTML"])
    parser.add_argument("--language", default="ch")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR.")
    parser.add_argument("--disable-formula", action="store_true")
    parser.add_argument("--page-ranges", help='Examples: "1-10", "2,4-6", "2--2".')
    parser.add_argument("--data-id")
    parser.add_argument("--extra-format", action="append", choices=["docx", "html", "latex"])
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=1800)
    return parser.parse_args()


def convert_input(input_value: str, output_dir: pathlib.Path, token: str, args: argparse.Namespace) -> dict:
    validate_input(input_value)
    output_dir.mkdir(parents=True, exist_ok=True)
    if is_url(input_value):
        task_id = submit_url(input_value, token, args)
        write_submission(output_dir, {"kind": "url", "value": input_value, "task_id": task_id})
        task_data = poll_url_task(task_id, token, args)
        source = {"kind": "url", "value": input_value, "task_id": task_id}
    else:
        file_path = pathlib.Path(input_value).expanduser().resolve()
        batch_id = submit_local(file_path, token, args)
        write_submission(output_dir, {"kind": "local_file", "file_name": file_path.name, "batch_id": batch_id})
        task_data = poll_batch(batch_id, token, args)
        source = {"kind": "local_file", "file_name": file_path.name, "batch_id": batch_id}

    zip_url = task_data.get("full_zip_url")
    if not zip_url:
        raise RuntimeError("MinerU completed but did not return full_zip_url")

    zip_path = output_dir / "mineru_result.zip"
    download_file(zip_url, zip_path)
    extracted = unpack_zip(zip_path, output_dir)

    manifest = {
        "source": source,
        "model_version": args.model_version,
        "language": args.language,
        "ocr": args.ocr,
        "page_ranges": args.page_ranges,
        "zip_path": str(zip_path),
        "extracted_files": extracted,
    }
    write_manifest(output_dir, manifest)
    return {"output_dir": str(output_dir), "manifest": str(output_dir / "mineru_manifest.json")}


def main() -> int:
    args = parse_args()
    validate_input(args.input)
    try:
        token = read_token(args.token_stdin)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        result = convert_input(
            args.input,
            pathlib.Path(args.output).expanduser().resolve(),
            token,
            args,
        )
    finally:
        del token
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
