#!/usr/bin/env python3
"""
Modern-TK80-Inference entry point.

Thin CLI wrapper around the interconnector. Prefer the Python API in
drivers.interconnector for programmatic use.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from drivers.interconnector import Interconnector, InterconnectorError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tk80")


def main() -> int:
    """Parse CLI args, connect, and optionally load or generate.

    Returns:
        0 on success, 1 on error.
    """
    parser = argparse.ArgumentParser(description="Modern-TK80-Inference")
    parser.add_argument("--dies", type=str, default=None, help="Comma-separated die indices")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--advertise", action="store_true", help="Print cluster advertisement and exit")
    parser.add_argument("--load", type=str, default=None, help="Model path or HF id")
    parser.add_argument("--backend", type=str, default="llama", choices=["llama", "pytorch"])
    parser.add_argument("--modality", type=str, default="llm", choices=["llm", "image", "voice", "agent"])
    parser.add_argument("--die", type=int, default=0)
    parser.add_argument("--split", type=str, default="single", choices=["single", "dual", "layer"])
    parser.add_argument("--prompt", type=str, default=None)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.7)
    args = parser.parse_args()

    die_indices = None
    if args.dies:
        try:
            die_indices = [int(x.strip()) for x in args.dies.split(",") if x.strip()]
        except ValueError:
            log.error("Invalid --dies value")
            return 1

    try:
        ic = Interconnector(die_indices=die_indices)
    except InterconnectorError as e:
        log.error("%s", e)
        return 1

    if args.advertise and not args.load:
        print(json.dumps(ic.advertise(), indent=2))
        return 0

    if args.status and not args.load and not args.prompt:
        print(json.dumps(ic.status(), indent=2))
        return 0

    if args.load:
        try:
            ic.load(
                args.load,
                backend=args.backend,
                modality=args.modality,
                die=args.die,
                split=args.split,
            )
        except (InterconnectorError, ValueError) as e:
            log.error("Load failed: %s", e)
            return 1

    if args.prompt:
        try:
            request = {
                "prompt": args.prompt,
                "max_tokens": args.max_tokens,
                "temperature": args.temperature,
            }
            result = ic.generate(request, die=args.die)
            if isinstance(result, str):
                print(result)
            else:
                print(result)
        except InterconnectorError as e:
            log.error("Generate failed: %s", e)
            return 1

    if not args.prompt:
        print(json.dumps(ic.status(), indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
