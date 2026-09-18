"""Command line interface: serve the API, run planning once, or seed sample data."""
from __future__ import annotations

import argparse
import json
import os
import sys


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "meridian.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


def cmd_run(args: argparse.Namespace) -> None:
    from meridian.agents.orchestrator import plan_from_catalog
    from meridian.core.config import get_settings
    from meridian.core.logging import configure_logging
    from meridian.data.loader import CatalogError
    from meridian.store.db import init_db

    settings = get_settings()
    configure_logging(settings.log_level)
    init_db(settings.database_url)
    try:
        summary = plan_from_catalog(
            settings=settings,
            data_dir=settings.data_dir,
            horizon_days=args.horizon,
            service_level=args.service_level,
            requested_by="cli",
        )
    except CatalogError as exc:
        print(f"catalog error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(summary, indent=2, default=str))


def cmd_seed(args: argparse.Namespace) -> None:
    from meridian.data.generate_sample_data import generate

    generate(args.data_dir)
    print(f"sample data written to {args.data_dir}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="meridian", description="Meridian supply chain agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="start the API server")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_run = sub.add_parser("run", help="execute one planning run and print the summary")
    p_run.add_argument("--horizon", type=int, default=None)
    p_run.add_argument("--service-level", type=float, default=None)
    p_run.set_defaults(func=cmd_run)

    p_seed = sub.add_parser("seed", help="generate the sample dataset")
    p_seed.add_argument("--data-dir", default=os.environ.get("MERIDIAN_DATA_DIR", "data"))
    p_seed.set_defaults(func=cmd_seed)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
