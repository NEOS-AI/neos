"""`python -m neos.bridge` -- 기기 브리지를 돌린다 (트랙 Q16a · Q16b · Q16c).

토큰은 **환경변수로만** 받는다(`NEOS_BRIDGE_TOKEN`) -- 명령줄 인자는 프로세스 목록에 남는다.
쓰기는 `--allow-writes` 를 줄 때만 선언한다. NEOS 쪽 자격증명도 `allow_writes` 여야 받아진다(BW2).
명령은 `--allow-commands pytest,ruff` 처럼 실행 파일을 이름으로 댈 때만 선언한다 -- NEOS 쪽 자격증명의
`allow_commands` 와 운영자의 서버 상한도 있어야 받아진다(Q16c BC2 · BC3).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from neos.bridge.client import run_bridge
from neos.bridge.tools import LocalReadOnlyTools, LocalWritableTools

TOKEN_ENV = "NEOS_BRIDGE_TOKEN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m neos.bridge",
        description="Share one folder of this device with NEOS (read-only unless --allow-writes).",
    )
    parser.add_argument("--url", required=True, help="wss://<host>/api/v1/coding/device-bridge/ws")
    parser.add_argument("--root", required=True, help="the one folder NEOS may read")
    parser.add_argument("--max-read-bytes", type=int, default=262_144)
    parser.add_argument("--max-list-entries", type=int, default=500)
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="also offer write_file (every write still asks you in NEOS)",
    )
    parser.add_argument("--max-write-bytes", type=int, default=262_144)
    parser.add_argument(
        "--allow-commands",
        default="",
        metavar="EXE[,EXE...]",
        help="also offer run_command for these executables only (every command still asks you in NEOS)",
    )
    parser.add_argument("--max-command-seconds", type=float, default=60.0)
    parser.add_argument("--max-command-output-bytes", type=int, default=65_536)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print(f"set {TOKEN_ENV} to the token NEOS showed when you paired this device", file=sys.stderr)
        return 2
    if not args.url.startswith("wss://") and not args.url.startswith("ws://localhost"):
        print("refusing a non-TLS URL (use wss://, or ws://localhost for development)", file=sys.stderr)
        return 2
    limits = {"max_read_bytes": args.max_read_bytes, "max_list_entries": args.max_list_entries}
    try:
        if args.allow_writes:
            tools = LocalWritableTools(args.root, max_write_bytes=args.max_write_bytes, **limits)
        else:
            tools = LocalReadOnlyTools(args.root, **limits)
        allowed = [name.strip() for name in args.allow_commands.split(",") if name.strip()]
        if allowed:
            # Q16c: 프로세스를 띄우는 모듈은 이 플래그가 있을 때만 import 한다.
            from neos.bridge.commands import CommandRunner

            tools = CommandRunner(
                tools,
                allowed,
                max_output_bytes=args.max_command_output_bytes,
                max_timeout_sec=args.max_command_seconds,
            )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    offered = ", ".join(entry["name"] for entry in tools.declaration())
    mode = "read and write" if args.allow_writes else "read-only"
    if allowed:
        mode += f", commands: {', '.join(sorted(tools.executables))}"
    print(f"sharing {tools.root} {mode} ({offered}). Ctrl-C to stop.")
    try:
        return asyncio.run(run_bridge(args.url, token, tools))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
