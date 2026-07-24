"""Flask routes: serve / download files under SHOT/<N>/ safely."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Callable, Optional

from mast_freegsnke_ui import artifacts as art


def register_shot_file_routes(server: Any, *, runs_dir: Path, runs_dir_getter: Optional[Callable[[], Path]] = None) -> None:
    """Register ``/shot-file/<shot>/<path:rel>`` on the Dash/Flask server."""

    def _runs() -> Path:
        if runs_dir_getter is not None:
            return Path(runs_dir_getter()).resolve()
        return Path(runs_dir).resolve()

    @server.route("/shot-file/<int:shot>/<path:rel>")
    def shot_file(shot: int, rel: str):  # type: ignore[no-untyped-def]
        from flask import abort, request, send_file

        run_dir = art.run_dir_for(_runs(), shot)
        if not run_dir.is_dir():
            abort(404)
        path = art.safe_resolve_under(run_dir, rel)
        if path is None:
            abort(404)
        mime, _ = mimetypes.guess_type(str(path))
        as_attachment = request.args.get("download") in {"1", "true", "yes"}
        return send_file(
            path,
            mimetype=mime or "application/octet-stream",
            as_attachment=as_attachment,
            download_name=path.name if as_attachment else None,
            max_age=2,
        )

    @server.route("/shot-zip/<int:shot>")
    def shot_zip(shot: int):  # type: ignore[no-untyped-def]
        from flask import abort, send_file
        import io

        run_dir = art.run_dir_for(_runs(), shot)
        if not run_dir.is_dir():
            abort(404)
        raw = art.build_run_zip_bytes(run_dir)
        return send_file(
            io.BytesIO(raw),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"SHOT_{shot}_artifacts.zip",
            max_age=0,
        )
