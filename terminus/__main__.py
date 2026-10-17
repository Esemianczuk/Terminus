"""Run ``python -m terminus serve``; reveal pairing only with the token command."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import secrets

from .api import create_app, loopback_host


def main(argv=None):
    parser = argparse.ArgumentParser(prog="terminus")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the shared local organism")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8769)
    serve.add_argument("--data-dir", default=".local")
    serve.add_argument("--seed", type=int, default=None, help="Explicit seed for reproducible new creatures")
    serve.add_argument("--allow-network", action="store_true",
                       help="Explicitly allow a non-loopback bind; pairing remains required")
    token = commands.add_parser("token", help="Show the private pairing token in this terminal")
    token.add_argument("--data-dir", default=".local")
    args = parser.parse_args(argv)
    if args.command == "token":
        path = Path(args.data_dir) / "token"
        if not path.is_file():
            parser.error("Start Terminus once to create its private pairing token")
        print(path.read_text().strip())
        return
    if not loopback_host(args.host) and not args.allow_network:
        parser.error("A non-loopback host needs --allow-network; every client must still pair")
    import uvicorn
    uvicorn.run(create_app(args.data_dir, seed=args.seed if args.seed is not None else secrets.randbits(63)), host=args.host, port=args.port,
                access_log=False, log_level="info", ws_max_size=8192)


if __name__ == "__main__":
    main()
