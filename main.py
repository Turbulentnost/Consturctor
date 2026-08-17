#!/usr/bin/env python3
"""CLI entry point for the Constructor coding agent."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from agent.llm_client import create_llm_client, load_config_from_env
from agent.loop import run_agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Constructor coding agent (tool-calling runtime)")
    parser.add_argument("task", nargs="?", help="User goal / task description")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: AGENT_WORKSPACE env or current directory)",
    )
    parser.add_argument("--mock", action="store_true", help="Force MockLLMClient (offline demo)")
    parser.add_argument("--debug", action="store_true", help="Verbose tool trace logging")
    parser.add_argument("--max-steps", type=int, default=None, help="Override AGENT_MAX_STEPS")
    args = parser.parse_args(argv)

    if not args.task:
        parser.error("task is required")

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = load_config_from_env(args.workspace)
    if args.debug:
        config.debug = True
    if args.max_steps is not None:
        config.max_steps = args.max_steps
    if args.mock:
        config.provider = "mock"
        config.api_key = None

    Path(config.workspace_root).mkdir(parents=True, exist_ok=True)
    llm = create_llm_client(config)
    result = run_agent(args.task, config, llm)

    print("\n=== Agent finished ===")
    print(f"Steps: {result.steps}")
    if result.aborted:
        print(f"Aborted: {result.abort_reason}")
    print(f"\nAnswer:\n{result.final_answer or '(empty)'}\n")
    return 1 if result.aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
