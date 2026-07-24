"""Dash application: shot-only run + stable results browser."""
from __future__ import annotations

import hashlib
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, List, Optional

from mast_freegsnke_ui import artifacts as art
from mast_freegsnke_ui import panels
from mast_freegsnke_ui.file_server import register_shot_file_routes
from mast_freegsnke_ui.run_manager import RunManager

_dash = None
_dbc = None
_html = None
_dcc = None
_Input = None
_Output = None
_State = None
_no_update = None

_POLL_IDLE_MS = 2500


def _require_dash() -> None:
    global _dash, _dbc, _html, _dcc, _Input, _Output, _State, _no_update
    if _dash is not None:
        return
    try:
        import dash
        from dash import Input, Output, State, dcc, html, no_update
        import dash_bootstrap_components as dbc
    except ImportError as e:
        raise SystemExit(
            "UI dependencies missing. Install with:\n"
            '  python -m pip install -e ".[ui]"\n'
            f"Original error: {e}"
        ) from e
    _dash = dash
    _dbc = dbc
    _html = html
    _dcc = dcc
    _Input = Input
    _Output = Output
    _State = State
    _no_update = no_update


def _status_color(status: str) -> str:
    s = (status or "idle").lower()
    if s in {"success", "ok", "completed"}:
        return "success"
    if s in {"failed", "error"}:
        return "danger"
    if s in {"running", "started"}:
        return "warning"
    if s == "cancelled":
        return "secondary"
    return "secondary"


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _library_fingerprint(runs_dir: Path) -> str:
    # Cheap: shot folder names only (no per-file stats).
    try:
        return _hash_text("|".join(str(s) for s in art.list_shot_dirs(runs_dir)))
    except OSError:
        return ""


def _shot_library_options(runs_dir: Path, *, cache_dir: Optional[Path] = None, required_groups: Optional[List[str]] = None) -> List[dict]:
    # Labels stay light — status is visible after Open / in the badge.
    from mast_freegsnke_ui.level2 import shot_cache_status

    opts = []
    req = list(required_groups or ("pf_active", "magnetics", "wall"))
    for s in art.list_shot_dirs(runs_dir):
        label = str(s)
        if cache_dir is not None:
            st = shot_cache_status(cache_dir, s, required=req)
            if st.get("ready"):
                label = f"{s}  ·  cache ready"
            elif st.get("partial"):
                label = f"{s}  ·  cache partial"
        opts.append({"label": label, "value": int(s)})
    return opts


def _stage_sig(progress: Optional[dict], running: bool) -> str:
    if not progress:
        return f"empty|{running}"
    stages = progress.get("stage_log") or []
    tail = ""
    if stages and isinstance(stages[-1], dict):
        last = stages[-1]
        tail = f"{last.get('stage')}:{last.get('ok')}:{last.get('error')}"
    return f"{running}|{progress.get('status')}|{progress.get('current_stage')}|{len(stages)}|{tail}"


def create_app(
    *,
    repo_root: Path,
    runs_dir: Path,
    config_path: Path,
    run_manager: Optional[RunManager] = None,
) -> Any:
    _require_dash()
    dash, dbc, html, dcc = _dash, _dbc, _html, _dcc
    Input, Output, State, no_update = _Input, _Output, _State, _no_update

    repo_root = Path(repo_root).resolve()
    runs_dir = Path(runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = (repo_root / runs_dir).resolve()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    cache_dir = (repo_root / "data_cache").resolve()
    required_groups = ["pf_active", "magnetics", "wall"]
    try:
        import json as _json

        if config_path.is_file():
            cfg_obj = _json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(cfg_obj, dict):
                if cfg_obj.get("cache_dir"):
                    cd = Path(str(cfg_obj["cache_dir"]))
                    cache_dir = cd if cd.is_absolute() else (repo_root / cd).resolve()
                if isinstance(cfg_obj.get("required_groups"), list) and cfg_obj["required_groups"]:
                    required_groups = [str(x) for x in cfg_obj["required_groups"]]
    except Exception:
        pass

    manager = run_manager or RunManager()
    assets_path = str(Path(__file__).resolve().parent / "assets")
    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.CYBORG],
        assets_folder=assets_path,
        suppress_callback_exceptions=True,
        title="Fair-MAST → FreeGSNKE",
        update_title=None,
    )
    register_shot_file_routes(app.server, runs_dir=runs_dir)

    empty_body = panels.fill_one_tab("overview", None, None)
    library_opts = _shot_library_options(runs_dir, cache_dir=cache_dir, required_groups=required_groups)
    library_fp = _library_fingerprint(runs_dir)

    app.layout = dbc.Container(
        [
            dcc.Store(id="active-shot", data=None),
            dcc.Store(id="ui-status", data="idle"),
            dcc.Store(id="refresh-token", data=0),
            dcc.Store(id="poll-cache", data={}),
            dcc.Store(id="library-fp", data=library_fp),
            dcc.Interval(id="poll", interval=_POLL_IDLE_MS, n_intervals=0),
            html.Header(
                [
                    html.Div(
                        [
                            html.P("MAST reconstruction console", className="fg-eyebrow"),
                            html.H1(["Fair-MAST ", html.Span("→ FreeGSNKE")], className="fg-brand"),
                            html.P(
                                "Shot-only workflow: enter a MAST shot number. Download, authorities, FreeGSNKE, "
                                "residuals, and EFIT archive compare run automatically.",
                                className="fg-sub",
                            ),
                            html.Div(
                                [
                                    html.Span([html.Strong("Solver"), " FreeGSNKE"], className="fg-meta-chip"),
                                    html.Span([html.Strong("EFIT"), " archive compare · ADR-002"], className="fg-meta-chip"),
                                    html.Span([html.Strong("Authority"), " fail-fast"], className="fg-meta-chip"),
                                ],
                                className="fg-meta-row",
                            ),
                        ],
                        className="fg-header-copy",
                    ),
                    html.Div(
                        [
                            dbc.Badge(id="status-badge", children="idle", color="secondary", className="status-chip"),
                            html.Div(id="status-detail", className="status-detail"),
                        ],
                        className="fg-header-status",
                    ),
                ],
                className="fg-header",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Span("1", className="step-num"),
                                        html.H6("Select shot", className="mb-0"),
                                    ],
                                    className="section-head",
                                ),
                                html.Div(
                                    [
                                        dbc.Label("Shot number", html_for="shot-input", className="fg-label"),
                                        dbc.InputGroup(
                                            [
                                                dbc.Input(
                                                    id="shot-input",
                                                    type="number",
                                                    min=1,
                                                    step=1,
                                                    placeholder="e.g. 30201",
                                                    debounce=True,
                                                    n_submit=0,
                                                ),
                                                dbc.Button("Open", id="btn-open", color="secondary", outline=True),
                                            ],
                                            className="mb-2",
                                        ),
                                        dbc.Label("Local library", html_for="shot-picker", className="fg-label"),
                                        dcc.Dropdown(
                                            id="shot-picker",
                                            options=library_opts,
                                            placeholder="Browse existing SHOT folders…",
                                            clearable=True,
                                            className="mb-1 shot-dropdown",
                                        ),
                                        html.P(
                                            "Open browses artifacts without re-running. Start archives prior SHOT output into history/, "
                                            "then runs the pipeline — local data_cache Level-2 groups are reused (only missing Zarrs sync).",
                                            className="fg-hint",
                                        ),
                                        html.Div(
                                            ["Press ", html.Kbd("Enter"), " in the shot field to Open"],
                                            className="kbd-hint",
                                        ),
                                    ],
                                    className="shot-controls",
                                ),
                                html.Div(
                                    [
                                        html.Span("2", className="step-num"),
                                        html.H6("Run", className="mb-0"),
                                    ],
                                    className="section-head mt-3",
                                ),
                                html.Div(
                                    [
                                        dbc.Button("Start run", id="btn-start", color="primary", className="me-2 flex-grow-1"),
                                        dbc.Button("Cancel", id="btn-cancel", color="danger", outline=True),
                                    ],
                                    className="d-flex mb-2",
                                ),
                                html.Div(id="run-alert"),
                                html.Div(id="blocking-banner"),
                                html.Div(id="shot-path", className="fg-path mb-2"),
                                html.Hr(className="fg-hr"),
                                html.Div(
                                    [
                                        html.Span("3", className="step-num"),
                                        html.H6("Progress", className="mb-0"),
                                        html.Span(id="stage-count", className="stage-count ms-auto"),
                                    ],
                                    className="section-head mb-2",
                                ),
                                html.Div(id="stage-progress", children=panels.stage_progress_bar(None, False)),
                                html.Div(
                                    id="stage-panel",
                                    children=panels.stage_timeline(None, False),
                                    className="stage-scroll",
                                ),
                                html.H6("Operator log", className="section-title mt-3"),
                                html.Pre(id="log-panel", children="Waiting for pipeline output…", className="log-panel p-2"),
                            ],
                            className="fg-panel fg-side",
                        ),
                        lg=4,
                        className="mb-3",
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Div(
                                            id="results-heading",
                                            children=panels.results_heading(None, "overview"),
                                        ),
                                        html.Div(
                                            [
                                                dbc.Button(
                                                    "Refresh",
                                                    id="btn-refresh",
                                                    color="secondary",
                                                    outline=True,
                                                    size="sm",
                                                    className="me-1",
                                                ),
                                                html.A(
                                                    "Download ZIP",
                                                    id="btn-zip-link",
                                                    href="#",
                                                    className="btn btn-sm btn-success disabled",
                                                ),
                                            ],
                                            className="d-flex results-toolbar",
                                        ),
                                    ],
                                    className="d-flex justify-content-between align-items-start mb-3 gap-2 flex-wrap",
                                ),
                                dcc.Tabs(
                                    id="results-tabs",
                                    value="overview",
                                    persistence=False,
                                    className="results-dcc-tabs",
                                    parent_className="results-dcc-tabs-parent",
                                    children=[
                                        dcc.Tab(
                                            label=label,
                                            value=tid,
                                            className="results-dcc-tab",
                                            selected_className="results-dcc-tab--selected",
                                        )
                                        for tid, label in panels.TAB_DEFS
                                    ],
                                ),
                                dcc.Loading(
                                    id="tab-loading",
                                    type="dot",
                                    color="#2fb9a8",
                                    children=html.Div(
                                        id="tab-body",
                                        children=empty_body,
                                        className="tab-pane-body",
                                    ),
                                ),
                            ],
                            className="fg-panel fg-results",
                        ),
                        lg=8,
                        className="mb-3",
                    ),
                ],
                className="g-3",
            ),
            html.Footer(
                [
                    html.Div(
                        f"config {config_path.as_posix()}  ·  library {runs_dir.as_posix()}"
                    ),
                    html.Div(
                        "shot-only happy path  ·  EFIT = FAIR-MAST archive compare (ADR-002)  ·  Enter opens  ·  Start reconstructs",
                        className="fg-footer-keys",
                    ),
                ],
                className="fg-footer",
            ),
        ],
        fluid=True,
        className="fg-shell px-3 pb-4",
    )

    # Adaptive poll rate (clientside — no server round-trip churn).
    app.clientside_callback(
        """
        function(status) {
            if (status === 'running' || status === 'started') {
                return 900;
            }
            return 2500;
        }
        """,
        Output("poll", "interval"),
        Input("ui-status", "data"),
    )

    @app.callback(
        Output("results-tabs", "value"),
        Input("active-shot", "data"),
        prevent_initial_call=True,
    )
    def on_shot_reset_tab(_shot):
        """Always land on Overview when the active shot changes."""
        return "overview"

    def _resolve_shot(shot_val: Any, picker_val: Any) -> Optional[int]:
        if shot_val is not None and str(shot_val).strip() != "":
            try:
                return int(shot_val)
            except (TypeError, ValueError):
                pass
        if picker_val is not None and str(picker_val).strip() != "":
            try:
                return int(picker_val)
            except (TypeError, ValueError):
                pass
        return None

    def _open_shot(shot: int):
        rd = art.run_dir_for(runs_dir, shot)
        if not rd.is_dir():
            return (
                dbc.Alert(
                    [
                        html.Strong(f"No folder at {rd.as_posix()}"),
                        html.Div("Start a run to download & reconstruct, or pick another shot from the library."),
                    ],
                    color="danger",
                ),
                None,
                "idle",
                manager.is_running,
                shot,
                "",
            )
        man = art.load_manifest(rd) or {}
        st = str(man.get("status") or "?")
        from mast_freegsnke_ui.level2 import shot_cache_status

        cache_st = shot_cache_status(cache_dir, shot, required=required_groups)
        if cache_st.get("ready"):
            cache_txt = "Level-2 cache ready (Start will skip S3 for cached groups)"
        elif cache_st.get("partial"):
            miss = ", ".join(cache_st.get("missing_required") or [])
            cache_txt = f"Level-2 cache partial — missing: {miss or '?'}"
        else:
            cache_txt = "Level-2 cache empty — Start will download required groups"
        return (
            dbc.Alert(
                [
                    html.Strong(f"Opened SHOT/{shot}"),
                    html.Span(f" · status={st}"),
                    html.Div(
                        "Tabs: Overview · Level-2 (plots+CSV) · Residuals · EFIT · GIFs · Authorities · Files.",
                        className="small mt-1",
                    ),
                    html.Div(cache_txt, className="small text-muted"),
                ],
                color="info",
                duration=5000,
            ),
            shot,
            "idle",
            manager.is_running,
            shot,
            rd.as_posix(),
        )

    @app.callback(
        Output("run-alert", "children"),
        Output("active-shot", "data"),
        Output("ui-status", "data"),
        Output("btn-start", "disabled"),
        Output("shot-input", "value"),
        Output("shot-path", "children"),
        Input("shot-picker", "value"),
        prevent_initial_call=True,
    )
    def on_picker(picker_val):
        if picker_val is None:
            return no_update, no_update, no_update, no_update, no_update, no_update
        return _open_shot(int(picker_val))

    @app.callback(
        Output("run-alert", "children", allow_duplicate=True),
        Output("active-shot", "data", allow_duplicate=True),
        Output("ui-status", "data", allow_duplicate=True),
        Output("btn-start", "disabled", allow_duplicate=True),
        Output("shot-input", "value", allow_duplicate=True),
        Output("shot-path", "children", allow_duplicate=True),
        Input("btn-open", "n_clicks"),
        Input("btn-start", "n_clicks"),
        Input("btn-cancel", "n_clicks"),
        Input("shot-input", "n_submit"),
        State("shot-input", "value"),
        State("shot-picker", "value"),
        State("active-shot", "data"),
        State("ui-status", "data"),
        prevent_initial_call=True,
    )
    def on_buttons(n_open, n_start, n_cancel, n_submit, shot_val, picker_val, active_shot, ui_status):
        ctx = dash.callback_context
        if not ctx.triggered:
            return (no_update,) * 6
        tid = ctx.triggered[0]["prop_id"].split(".")[0]

        if tid == "btn-cancel":
            if manager.is_running:
                manager.cancel()
                return (
                    dbc.Alert("Run cancelled.", color="warning", duration=3500),
                    active_shot,
                    "cancelled",
                    False,
                    no_update,
                    no_update,
                )
            return (
                dbc.Alert("Nothing to cancel.", color="secondary", duration=2200),
                active_shot,
                ui_status,
                False,
                no_update,
                no_update,
            )

        shot = _resolve_shot(shot_val, picker_val)
        if shot is None:
            return (
                dbc.Alert("Enter a MAST shot number.", color="warning", duration=3000),
                active_shot,
                ui_status,
                manager.is_running,
                no_update,
                no_update,
            )

        if tid in {"btn-open", "shot-input"}:
            return _open_shot(shot)

        if tid != "btn-start":
            return (no_update,) * 6

        if manager.is_running:
            return (
                dbc.Alert("A run is already in progress.", color="warning", duration=3000),
                active_shot,
                "running",
                True,
                shot,
                no_update,
            )
        try:
            manager.start(shot, config=config_path, cwd=repo_root)
        except Exception as e:  # noqa: BLE001
            return (
                dbc.Alert(f"Failed to start: {e}", color="danger"),
                active_shot,
                "failed",
                False,
                shot,
                no_update,
            )
        rd = art.run_dir_for(runs_dir, shot)
        return (
            dbc.Alert(
                [
                    html.Strong(f"Pipeline started for shot {shot}"),
                    html.Div("Watch Progress and Live log. Results refresh when the run finishes.", className="small mt-1"),
                ],
                color="primary",
                duration=4500,
            ),
            shot,
            "running",
            True,
            shot,
            rd.as_posix(),
        )

    @app.callback(
        Output("status-badge", "children"),
        Output("status-badge", "color"),
        Output("status-detail", "children"),
        Output("stage-progress", "children"),
        Output("stage-panel", "children"),
        Output("stage-count", "children"),
        Output("log-panel", "children"),
        Output("blocking-banner", "children"),
        Output("btn-start", "disabled", allow_duplicate=True),
        Output("ui-status", "data", allow_duplicate=True),
        Output("run-alert", "children", allow_duplicate=True),
        Output("refresh-token", "data"),
        Output("shot-picker", "options"),
        Output("btn-zip-link", "href"),
        Output("btn-zip-link", "className"),
        Output("shot-path", "children", allow_duplicate=True),
        Output("poll-cache", "data"),
        Output("library-fp", "data"),
        Input("poll", "n_intervals"),
        State("active-shot", "data"),
        State("ui-status", "data"),
        State("refresh-token", "data"),
        State("poll-cache", "data"),
        State("library-fp", "data"),
        prevent_initial_call=True,
    )
    def on_poll(_n, active_shot, ui_status, refresh_token, poll_cache, library_fp):
        snap = manager.snapshot()
        running = bool(snap["running"])
        shot = active_shot if active_shot is not None else snap.get("shot")
        run_dir = art.run_dir_for(runs_dir, int(shot)) if shot is not None else None
        progress = art.load_progress(run_dir) if run_dir else None
        man = art.load_manifest(run_dir) if run_dir else None
        cache = dict(poll_cache or {})

        status_label = ui_status or "idle"
        alert = no_update
        bump = no_update
        if running:
            status_label = "running"
        elif snap.get("returncode") is not None and ui_status == "running":
            rc = snap["returncode"]
            if rc == 0:
                status_label = "success"
                alert = dbc.Alert(
                    [
                        f"Run finished OK (SHOT/{shot}). ",
                        html.A("Download ZIP", href=f"/shot-zip/{int(shot)}", className="alert-link"),
                    ],
                    color="success",
                    duration=8000,
                )
                bump = int(refresh_token or 0) + 1
            elif rc == -1:
                status_label = "cancelled"
                bump = int(refresh_token or 0) + 1
            else:
                status_label = "failed"
                blocking = []
                if progress:
                    blocking = list(progress.get("blocking_errors") or [])
                if man:
                    blocking = list(man.get("blocking_errors") or blocking)
                alert = dbc.Alert(
                    [
                        html.Strong(f"Run failed (rc={rc}). "),
                        html.Div("; ".join(str(b) for b in blocking[:4]) if blocking else "See log / EXCEPTION_TRACEBACK.txt"),
                        html.Div(
                            "Open this shot to inspect partial results. Fix blocking issues, then Start again — prior output is archived under history/.",
                            className="small mt-1",
                        ),
                    ],
                    color="danger",
                )
                bump = int(refresh_token or 0) + 1
        elif progress and not running:
            st = str(progress.get("status") or status_label)
            if st in {"success", "failed", "running", "started"}:
                status_label = "running" if st == "started" else st
        elif man and not running and active_shot is not None:
            status_label = str(man.get("status") or status_label)

        log_text = "\n".join(snap.get("log_lines") or []) or "Waiting for pipeline output…"
        log_sig = _hash_text(log_text)
        stage_sig = _stage_sig(progress, running)

        blocking_ui: List[str] = []
        for src in (progress, man):
            if not src:
                continue
            for b in src.get("blocking_errors") or []:
                blocking_ui.append(str(b))
        block_sig = _hash_text("|".join(blocking_ui[:8]))

        zip_href = f"/shot-zip/{int(shot)}" if shot is not None else "#"
        zip_cls = "btn btn-sm btn-success" if shot is not None else "btn btn-sm btn-success disabled"
        path_txt = art.run_dir_for(runs_dir, int(shot)).as_posix() if shot is not None else ""

        detail = ""
        if running and progress and progress.get("current_stage"):
            detail = f"stage · {progress.get('current_stage')}"
        elif shot is not None:
            detail = f"shot {int(shot)}"

        # Skip DOM updates when nothing meaningful changed.
        out_badge = status_label if cache.get("status") != status_label else no_update
        out_color = _status_color(status_label) if cache.get("status") != status_label else no_update
        out_detail = detail if cache.get("detail") != detail else no_update

        if cache.get("stage_sig") != stage_sig:
            out_progress = panels.stage_progress_bar(progress, running=running)
            out_stage = panels.stage_timeline(progress, running=running)
            n_stages = len((progress or {}).get("stage_log") or [])
            out_count = f"{n_stages} stages" if n_stages else ""
        else:
            out_progress = no_update
            out_stage = no_update
            out_count = no_update

        out_log = log_text if cache.get("log_sig") != log_sig else no_update

        if cache.get("block_sig") != block_sig or (running and cache.get("running") != running):
            if blocking_ui and not running:
                out_banner = dbc.Alert(
                    [
                        html.Strong("Blocking errors (fail-fast — do not invent metrology)"),
                        html.Ul([html.Li(x) for x in blocking_ui[:6]], className="mb-0 mt-1 small"),
                    ],
                    color="danger",
                    className="py-2",
                )
            elif running:
                out_banner = None
            else:
                out_banner = None if not blocking_ui else no_update
        else:
            out_banner = no_update

        out_disabled = running if cache.get("running") != running else no_update
        next_ui = (
            status_label
            if running or snap.get("returncode") is not None
            else (status_label if active_shot else (ui_status or "idle"))
        )
        out_ui = next_ui if cache.get("ui") != next_ui else no_update

        new_lib_fp = library_fp
        out_opts = no_update
        # Refresh library only when the shot set / status mtimes change.
        if running or bump is not no_update or cache.get("lib_check", 0) >= 4:
            try:
                new_lib_fp = _library_fingerprint(runs_dir)
            except OSError:
                new_lib_fp = library_fp
            if new_lib_fp != library_fp:
                out_opts = _shot_library_options(runs_dir, cache_dir=cache_dir, required_groups=required_groups)
            lib_check = 0
        else:
            lib_check = int(cache.get("lib_check") or 0) + 1

        out_zip_href = zip_href if cache.get("zip_href") != zip_href else no_update
        out_zip_cls = zip_cls if cache.get("zip_cls") != zip_cls else no_update
        out_path = path_txt if cache.get("path") != path_txt else no_update
        out_lib_fp = new_lib_fp if new_lib_fp != library_fp else no_update

        new_cache = {
            "status": status_label,
            "detail": detail,
            "stage_sig": stage_sig,
            "log_sig": log_sig,
            "block_sig": block_sig,
            "running": running,
            "ui": next_ui,
            "zip_href": zip_href,
            "zip_cls": zip_cls,
            "path": path_txt,
            "lib_check": lib_check,
        }

        return (
            out_badge,
            out_color,
            out_detail,
            out_progress,
            out_stage,
            out_count,
            out_log,
            out_banner,
            out_disabled,
            out_ui,
            alert,
            bump,
            out_opts,
            out_zip_href,
            out_zip_cls,
            out_path,
            new_cache,
            out_lib_fp,
        )

    @app.callback(
        Output("results-heading", "children"),
        Output("tab-body", "children"),
        Input("active-shot", "data"),
        Input("results-tabs", "value"),
        Input("refresh-token", "data"),
        Input("btn-refresh", "n_clicks"),
        prevent_initial_call=False,
    )
    def on_results(active_shot, active_tab, _refresh_token, _n_refresh):
        """Fill the active tab from the current shot.

        When the shot changes, always render Overview even if the tab widget
        has not flipped yet (avoids showing Residuals/etc. for the new shot).
        """
        triggered = None
        try:
            triggered = dash.callback_context.triggered_id
        except Exception:
            triggered = None

        tid = (active_tab or "overview").strip().lower()
        if triggered == "active-shot":
            tid = "overview"
        valid = {k for k, _ in panels.TAB_DEFS}
        if tid not in valid:
            tid = "overview"

        run_dir = None
        shot_i = None
        if active_shot is not None:
            try:
                shot_i = int(active_shot)
            except (TypeError, ValueError):
                shot_i = None
            if shot_i is not None:
                candidate = art.run_dir_for(runs_dir, shot_i)
                if candidate.is_dir():
                    run_dir = candidate
        heading = panels.results_heading(shot_i, tid)
        body = panels.fill_one_tab(tid, shot_i, run_dir)
        return heading, body

    return app


def _open_browser(url: str, delay_s: float = 1.15) -> None:
    def _go() -> None:
        time.sleep(delay_s)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


def run_server(
    *,
    repo_root: Path,
    runs_dir: Path = Path("SHOT"),
    config_path: Path = Path("configs/default.json"),
    host: str = "127.0.0.1",
    port: int = 8050,
    debug: bool = False,
    open_browser: bool = True,
) -> None:
    import os

    app = create_app(repo_root=repo_root, runs_dir=runs_dir, config_path=config_path)
    url = f"http://{host}:{port}"
    print(f"[ui] Shot-only Dash UI → {url}")
    print(f"[ui] Library: {(Path(runs_dir) if Path(runs_dir).is_absolute() else (Path(repo_root) / runs_dir)).resolve()}")
    should_open = bool(open_browser) and (not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true")
    if should_open:
        _open_browser(url)
        print("[ui] Opening browser… (--no-browser to skip)")
    app.run(host=host, port=int(port), debug=bool(debug))
