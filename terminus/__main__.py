"""Run the local-only organism core."""

from __future__ import annotations

import argparse
import secrets

from .api import create_app


def main(argv=None):
    parser = argparse.ArgumentParser(prog="terminus")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local organism")
    serve.add_argument("--port", type=int, default=8769)
    serve.add_argument("--data-dir", default=".local")
    serve.add_argument("--seed", type=int, default=None, help="Explicit seed for reproducible new creatures")
    args = parser.parse_args(argv)
    import uvicorn
    uvicorn.run(create_app(args.data_dir, seed=args.seed if args.seed is not None else secrets.randbits(63)),
                host="127.0.0.1", port=args.port,
                access_log=False, log_level="info", ws_max_size=8192)


if __name__ == "__main__":
    main()
