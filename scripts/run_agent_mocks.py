"""Run mock AI agent scenarios against platform orchestrator (stub mode)."""

from __future__ import annotations

import argparse
import json
import sys

import httpx

ORCHESTRATOR_URL = "http://127.0.0.1:7825"


def list_scenarios(client: httpx.Client) -> list[dict]:
    response = client.get(f"{ORCHESTRATOR_URL}/api/v1/agent/mocks")
    response.raise_for_status()
    return response.json()["items"]


def simulate(client: httpx.Client, scenario_id: str) -> dict:
    response = client.post(
        f"{ORCHESTRATOR_URL}/api/v1/agent/mocks/{scenario_id}/simulate",
        json={"agent_id": f"mock-{scenario_id}", "department": "Demo", "user_id": "cli"},
    )
    response.raise_for_status()
    return response.json()


def print_result(result: dict) -> None:
    print(f"\n=== {result['title']} ({result['scenario_id']}) ===")
    print(f"status: {result['status']}")
    for step in result.get("steps", []):
        if step["phase"] == "plan":
            print(f"  PLAN: {step['message']}")
        elif step["phase"] == "tool":
            mark = "OK" if step.get("ok") else "FAIL"
            print(f"  TOOL [{mark}] {step['tool_name']}: {step.get('summary') or step.get('error')}")
        elif step["phase"] == "error":
            print(f"  ERROR {step['tool_name']}: {step.get('message')}")
    if result.get("errors"):
        print("errors:", "; ".join(result["errors"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mock agent tool scenarios")
    parser.add_argument("scenario", nargs="?", help="Scenario id or omit with --all")
    parser.add_argument("--all", action="store_true", help="Run all mock scenarios")
    parser.add_argument("--list", action="store_true", help="List scenarios")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    with httpx.Client(timeout=120.0) as client:
        if args.list:
            for item in list_scenarios(client):
                print(f"{item['id']:20} {item['title']} ({item['tool_count']} tools)")
            return 0

        if args.all:
            ids = [item["id"] for item in list_scenarios(client)]
        elif args.scenario:
            ids = [args.scenario]
        else:
            parser.print_help()
            return 1

        failed = 0
        for scenario_id in ids:
            try:
                result = simulate(client, scenario_id)
            except httpx.HTTPError as exc:
                print(f"\n=== {scenario_id} ===\nFAILED: {exc}", file=sys.stderr)
                failed += 1
                continue
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_result(result)
            if result.get("status") != "done":
                failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
