"""python -m mast_freegsnke_ui"""
from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from mast_freegsnke_ui.app import run_server

    ap = argparse.ArgumentParser(description="Fair-MAST → FreeGSNKE shot-only Dash UI")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--runs-dir", type=str, default="SHOT")
    ap.add_argument("--config", type=str, default="configs/default.json")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")
    ap.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="Repository root (default: cwd)",
    )
    args = ap.parse_args(argv)
    root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd().resolve()
    run_server(
        repo_root=root,
        runs_dir=Path(args.runs_dir),
        config_path=Path(args.config),
        host=args.host,
        port=args.port,
        debug=args.debug,
        open_browser=not bool(args.no_browser),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
