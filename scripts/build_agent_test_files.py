"""Write agent test docx/xlsx via fs.write or fs.build_office_file."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from platform_tool_filesystem.agent_build_files import (
    build_office_write_payload,
    default_test_payloads,
    resolve_output_dir,
)

DEFAULT_URL = os.environ.get("TOOL_DESKTOP_HOST_URL", "http://127.0.0.1:7830").rstrip("/")


def invoke_tool(base_url: str, tool_name: str, payload: dict) -> dict:
    url = f"{base_url.rstrip('/')}/api/v1/tools/{tool_name}/invoke"
    response = httpx.post(url, json={"payload": payload}, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or f"{tool_name} failed")
    return data["data"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create docx/xlsx via platform fs tools")
    parser.add_argument("--host", default=DEFAULT_URL, help="Desktop host URL (:7830)")
    parser.add_argument("--output-dir", help="Directory for default filenames")
    parser.add_argument("--docx-path", help="Full path for .docx")
    parser.add_argument("--xlsx-path", help="Full path for .xlsx")
    parser.add_argument("--path", help="Single file path; uses fs.build_office_file")
    parser.add_argument("--format", choices=("docx", "xlsx"), help="Format with --path")
    parser.add_argument("--title", default="Constructor agent test")
    parser.add_argument("--docx-only", action="store_true")
    parser.add_argument("--xlsx-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"Host: {args.host}")

    try:
        if args.path:
            payload = {
                "path": args.path,
                "format": args.format or "",
                "title": args.title,
            }
            result = invoke_tool(args.host, "fs.build_office_file", payload)
            print(
                json.dumps(
                    {
                        "path": result.get("path"),
                        "bytes": result.get("bytes"),
                        "format": result.get("format"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.output_dir:
            folder = Path(args.output_dir).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
        else:
            folder = resolve_output_dir(prefer_desktop=True)

        docx_payload, xlsx_payload, folder = default_test_payloads(
            output_dir=folder,
            docx_path=args.docx_path,
            xlsx_path=args.xlsx_path,
            title=args.title,
        )
        print(f"Target folder: {folder}")

        summary: dict[str, object] = {"output_dir": str(folder), "transport": "fs.write"}
        if not args.xlsx_only:
            docx_result = invoke_tool(args.host, "fs.write", docx_payload)
            summary["docx_path"] = docx_result.get("path")
            summary["docx_bytes"] = docx_result.get("bytes")
        if not args.docx_only:
            xlsx_result = invoke_tool(args.host, "fs.write", xlsx_payload)
            summary["xlsx_path"] = xlsx_result.get("path")
            summary["xlsx_bytes"] = xlsx_result.get("bytes")
    except httpx.HTTPError as exc:
        print(f"HTTP error: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"Tool error: {exc}")
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
