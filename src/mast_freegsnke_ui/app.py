"""Dash application: shot-only run + stable results browser."""
from __future__ import annotations

import hashlib
import threading
import time
import webbrowser
from collections import OrderedDict
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
_ALL = None
_no_update = None

_POLL_IDLE_MS = 4000
_TAB_BODY_CACHE_MAX = 32
_tab_body_cache: OrderedDict[str, Any] = OrderedDict()
_tab_body_lock = threading.Lock()
_lib_opts_cache: dict = {"fp": None, "opts": None}


def _tab_body_cache_get(key: str) -> Any:
    with _tab_body_lock:
        if key not in _tab_body_cache:
            return None
        _tab_body_cache.move_to_end(key)
        return _tab_body_cache[key]


def _tab_body_cache_put(key: str, value: Any) -> None:
    with _tab_body_lock:
        _tab_body_cache[key] = value
        _tab_body_cache.move_to_end(key)
        while len(_tab_body_cache) > _TAB_BODY_CACHE_MAX:
            _tab_body_cache.popitem(last=False)


def _cached_shot_library_options(
    runs_dir: Path,
    *,
    cache_dir: Optional[Path],
    required_groups: Optional[List[str]],
    library_fp: str,
) -> List[dict]:
    """Reuse shot-library dropdown options while the library fingerprint is unchanged."""
    if _lib_opts_cache.get("fp") == library_fp and _lib_opts_cache.get("opts") is not None:
        return list(_lib_opts_cache["opts"])
    opts = _shot_library_options(
        runs_dir, cache_dir=cache_dir, required_groups=required_groups
    )
    _lib_opts_cache["fp"] = library_fp
    _lib_opts_cache["opts"] = list(opts)
    return opts


def _require_dash() -> None:
    global _dash, _dbc, _html, _dcc, _Input, _Output, _State, _ALL, _no_update
    if _dash is not None:
        return
    try:
        import dash
        from dash import ALL, Input, Output, State, dcc, html, no_update
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
    _ALL = ALL
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


def _library_fingerprint(runs_dir: Path, *, cache_dir: Optional[Path] = None) -> str:
    """Fingerprint shot library + optional cache readiness so dropdown labels refresh.

    Uses a separate accumulator — never mutate the shot-id list while iterating it
    (appended ``shot:zarr:mtime`` tokens contain ``:`` and are illegal/ADS paths on Windows).
    """
    try:
        shots = [str(s) for s in art.list_shot_dirs(runs_dir)]
        parts: List[str] = list(shots)
        if cache_dir is not None and cache_dir.is_dir():
            for s in shots:
                shot_cache = cache_dir / f"shot_{s}"
                if not shot_cache.is_dir():
                    parts.append(f"{s}:nocache")
                    continue
                try:
                    children = sorted(shot_cache.iterdir())
                except OSError:
                    parts.append(f"{s}:unreadable")
                    continue
                for child in children:
                    if child.name.endswith(".zarr"):
                        try:
                            mtime = int(child.stat().st_mtime)
                        except OSError:
                            mtime = 0
                        parts.append(f"{s}:{child.name}:{mtime}")
        return _hash_text("|".join(parts))
    except OSError:
        return ""


def _parse_shot_number(raw: Any) -> Optional[int]:
    """Parse a MAST shot from text/number input; reject empty / non-positive."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    try:
        shot = int(float(s)) if "." in s else int(s)
    except (TypeError, ValueError):
        return None
    return shot if shot >= 1 else None


def _shot_library_options(runs_dir: Path, *, cache_dir: Optional[Path] = None, required_groups: Optional[List[str]] = None) -> List[dict]:
    # Expert labels: bare shot first so dropdown search matches typed numbers.
    from mast_freegsnke_ui.level2 import shot_cache_status

    opts = []
    req = list(required_groups or ("pf_active", "magnetics", "wall"))
    for s in art.list_shot_dirs(runs_dir):
        rd = art.run_dir_for(runs_dir, int(s))
        bits = [str(s)]
        if rd.is_dir():
            k = art.overview_kpis(rd)
            bits.append(str(k.get("status") or "?"))
            n_block = k.get("blocking_n")
            if isinstance(n_block, int) and n_block > 0:
                bits.append(f"{n_block} block")
        if cache_dir is not None:
            st = shot_cache_status(cache_dir, s, required=req)
            if st.get("ready"):
                bits.append("cache ready")
            elif st.get("partial"):
                bits.append("cache partial")
        opts.append({"label": "  ·  ".join(bits), "value": int(s)})
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
    ALL = _ALL
    dash = _dash

    repo_root = Path(repo_root).resolve()
    runs_dir = Path(runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = (repo_root / runs_dir).resolve()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    cache_dir = (repo_root / "data_cache").resolve()
    required_groups = ["pf_active", "magnetics", "wall"]
    config_load_warning: Optional[str] = None
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
        else:
            config_load_warning = f"Config not found: {config_path.as_posix()} — using built-in cache defaults"
    except Exception as e:
        config_load_warning = (
            f"Config parse failed ({type(e).__name__}: {e}) — using built-in cache defaults"
        )

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
    library_fp = _library_fingerprint(runs_dir, cache_dir=cache_dir)

    app.layout = dbc.Container(
        [
            dcc.Store(id="active-shot", data=None),
            dcc.Store(id="ui-status", data="idle"),
            dcc.Store(id="refresh-token", data=0),
            dcc.Store(id="poll-cache", data={}),
            dcc.Store(id="library-fp", data=library_fp),
            dcc.Store(id="compare-shot-a", data=None),
            dcc.Store(id="compare-shot-b", data=None),
            dcc.Store(id="compare-family-store", data="plasma"),
            dcc.Interval(id="poll", interval=_POLL_IDLE_MS, n_intervals=0),
            html.Header(
                [
                    html.Div(
                        [
                            html.P("Fusion reconstruction console", className="fg-eyebrow"),
                            html.H1(["Fair-MAST ", html.Span("→ FreeGSNKE")], className="fg-brand"),
                            html.P(
                                "Shot-only MAST equilibrium workflow for fusion experts: "
                                "Level-2 ingest, declared authorities, FreeGSNKE inverse/forward/evolutive, "
                                "contract residuals, and EFIT++ archive compare.",
                                className="fg-sub",
                            ),
                            html.Div(
                                [
                                    html.Span([html.Strong("Solver"), " FreeGSNKE"], className="fg-meta-chip"),
                                    html.Span([html.Strong("EFIT"), " archive · ADR-002"], className="fg-meta-chip"),
                                    html.Span([html.Strong("Authority"), " fail-fast"], className="fg-meta-chip"),
                                    html.Span([html.Strong("Cache"), " reuse Zarrs"], className="fg-meta-chip"),
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
            (
                dbc.Alert(
                    config_load_warning,
                    color="warning",
                    className="mb-2 py-2 small",
                    dismissable=True,
                )
                if config_load_warning
                else None
            ),
            html.Div(
                id="shot-dossier",
                children=panels.shot_dossier(None, None),
                className="shot-dossier-bar mb-3",
            ),
            dcc.Store(id="kbd-bound", data=False),
            html.Div(id="kbd-sink", style={"display": "none"}),
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Span("Workflow", className="side-kicker"),
                                        html.H6("Shot control", className="mb-0 side-title"),
                                    ],
                                    className="section-head",
                                ),
                                html.Div(
                                    [
                                        dbc.Label("MAST shot number", html_for="shot-input", className="fg-label"),
                                        dbc.InputGroup(
                                            [
                                                dbc.Input(
                                                    id="shot-input",
                                                    type="text",
                                                    placeholder="e.g. 30201 — new or existing",
                                                    debounce=False,
                                                    n_submit=0,
                                                    className="shot-number-input",
                                                    persistence=False,
                                                ),
                                                dbc.Button(
                                                    "Open",
                                                    id="btn-open",
                                                    color="secondary",
                                                    outline=True,
                                                    title="Browse existing SHOT/<N>/ without re-running",
                                                ),
                                            ],
                                            className="mb-1",
                                        ),
                                        html.Div(
                                            "Type any MAST shot here, then Open or Reconstruct. New shots need Reconstruct.",
                                            className="action-hint mb-2",
                                        ),
                                        dbc.Label("Local SHOT library", html_for="shot-picker", className="fg-label"),
                                        dcc.Dropdown(
                                            id="shot-picker",
                                            options=library_opts,
                                            placeholder="Search existing SHOT folders…",
                                            clearable=True,
                                            searchable=True,
                                            className="mb-1 shot-dropdown",
                                        ),
                                        html.Div(
                                            "Browse-only list of folders already under SHOT/ — type a new number in the field above.",
                                            className="action-hint mb-2",
                                        ),
                                        html.Div(
                                            [
                                                html.Div(
                                                    [
                                                        html.Strong("Open"),
                                                        " — inspect artifacts only",
                                                    ],
                                                    className="action-hint",
                                                ),
                                                html.Div(
                                                    [
                                                        html.Strong("Reconstruct"),
                                                        " — archive prior output, run pipeline (cache reused)",
                                                    ],
                                                    className="action-hint",
                                                ),
                                            ],
                                            className="action-hints mb-2",
                                        ),
                                        html.Div(
                                            ["Enter", html.Kbd("⏎"), "opens · Start reconstructs · / focuses shot"],
                                            className="kbd-hint",
                                        ),
                                    ],
                                    className="shot-controls",
                                ),
                                html.Div(
                                    [
                                        dbc.Button(
                                            "Reconstruct",
                                            id="btn-start",
                                            color="primary",
                                            className="me-2 flex-grow-1",
                                            title="Run full Fair-MAST → FreeGSNKE pipeline for this shot",
                                        ),
                                        dbc.Button("Cancel", id="btn-cancel", color="danger", outline=True),
                                    ],
                                    className="d-flex mb-2 run-actions",
                                ),
                                html.Div(id="run-alert"),
                                html.Div(id="blocking-banner"),
                                html.Div(id="shot-path", className="fg-path mb-2"),
                                html.Hr(className="fg-hr"),
                                html.Div(
                                    [
                                        html.Span("Stages", className="side-kicker"),
                                        html.H6("Progress", className="mb-0 side-title"),
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
                                html.Div(
                                    [
                                        html.Span("Log", className="side-kicker"),
                                        html.H6("Operator output", className="mb-0 side-title"),
                                    ],
                                    className="section-head mt-3 mb-2",
                                ),
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
                                                    title="Reload artifacts from disk",
                                                ),
                                                html.A(
                                                    "Download ZIP",
                                                    id="btn-zip-link",
                                                    href="#",
                                                    className="btn btn-sm btn-success disabled",
                                                    title="Pack plots, CSV, JSON for this shot",
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
                                html.Div(
                                    id="tab-body",
                                    children=empty_body,
                                    className="tab-pane-body",
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
                        "Open = browse  ·  Reconstruct = pipeline  ·  / shot  ·  1–9 tabs  ·  r refresh  ·  "
                        "EFIT = archive (ADR-002)  ·  GSFit = live peer (ADR-006)  ·  copy buttons = clipboard",
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
                return 1100;
            }
            return 4000;
        }
        """,
        Output("poll", "interval"),
        Input("ui-status", "data"),
    )

    # Keyboard shortcuts + clipboard for [data-clipboard-text] (bound once).
    app.clientside_callback(
        """
        function(n, bound, refresh) {
            if (!window.__fgConsoleBound) {
                window.__fgConsoleBound = true;
                window.__fgPendingTab = null;
                window.__fgPendingRefresh = false;
                const tabs = ['overview','level2','residuals','planner','compare','efit','gsfit','gifs','auth','files'];
                document.addEventListener('keydown', function(e) {
                    const tag = (e.target && e.target.tagName) || '';
                    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (e.target && e.target.isContentEditable)) {
                        return;
                    }
                    if (e.key === '/') {
                        e.preventDefault();
                        const el = document.getElementById('shot-input');
                        if (el) { el.focus(); if (el.select) el.select(); }
                    }
                    if (e.key === 'r' || e.key === 'R') {
                        window.__fgPendingRefresh = true;
                    }
                    if (e.key >= '1' && e.key <= '9') {
                        window.__fgPendingTab = tabs[parseInt(e.key, 10) - 1] || null;
                    }
                });
                document.addEventListener('click', function(e) {
                    const btn = e.target && e.target.closest ? e.target.closest('[data-clipboard-text]') : null;
                    if (!btn) return;
                    const text = btn.getAttribute('data-clipboard-text') || '';
                    if (!text) return;
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(text).catch(function(){});
                    }
                    btn.classList.add('fg-copy-flash');
                    setTimeout(function(){ btn.classList.remove('fg-copy-flash'); }, 600);
                });
            }
            const outTab = window.__fgPendingTab;
            window.__fgPendingTab = null;
            const doRefresh = window.__fgPendingRefresh;
            window.__fgPendingRefresh = false;
            return [
                outTab ? outTab : window.dash_clientside.no_update,
                doRefresh ? ((refresh || 0) + 1) : window.dash_clientside.no_update,
                true
            ];
        }
        """,
        Output("results-tabs", "value", allow_duplicate=True),
        Output("refresh-token", "data", allow_duplicate=True),
        Output("kbd-bound", "data"),
        Input("poll", "n_intervals"),
        State("kbd-bound", "data"),
        State("refresh-token", "data"),
        prevent_initial_call=True,
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
        parsed = _parse_shot_number(shot_val)
        if parsed is not None:
            return parsed
        return _parse_shot_number(picker_val)

    def _dossier_for(shot: Optional[int]) -> Any:
        if shot is None:
            return panels.shot_dossier(None, None)
        rd = art.run_dir_for(runs_dir, int(shot))
        if not rd.is_dir():
            return panels.shot_dossier(None, None)
        from mast_freegsnke_ui.level2 import shot_cache_status

        cache_st = shot_cache_status(cache_dir, int(shot), required=required_groups)
        if cache_st.get("ready"):
            note = "Level-2 required groups cached — Reconstruct skips S3 for those Zarrs"
            cache_status = "ready"
        elif cache_st.get("partial"):
            miss = ", ".join(cache_st.get("missing_required") or [])
            note = f"Level-2 cache partial — missing: {miss or '?'}"
            cache_status = "partial"
        else:
            note = "Level-2 cache empty — Reconstruct will download required groups"
            cache_status = "empty"
        return panels.shot_dossier(
            int(shot), rd, cache_status=cache_status, cache_note=note
        )

    def _open_shot(shot: int):
        rd = art.run_dir_for(runs_dir, shot)
        if not rd.is_dir():
            return (
                dbc.Alert(
                    [
                        html.Strong(f"No folder at {rd.as_posix()}"),
                        html.Div("Reconstruct to download & solve, or pick another shot from the library."),
                    ],
                    color="danger",
                ),
                None,
                "idle" if not manager.is_running else no_update,
                manager.is_running,
                str(int(shot)),
                "",
                panels.shot_dossier(None, None),
            )
        if manager.is_running and manager.shot is not None and int(manager.shot) != int(shot):
            return (
                dbc.Alert(
                    [
                        html.Strong(f"Run in progress for shot {manager.shot}"),
                        html.Div(
                            f"Cannot bind the console to SHOT/{shot} while another reconstruction is live. "
                            "Cancel first, or wait for completion."
                        ),
                    ],
                    color="warning",
                    duration=6000,
                ),
                no_update,
                no_update,
                True,
                no_update,
                no_update,
                no_update,
            )
        man = art.load_manifest(rd) or {}
        st = str(man.get("status") or "?")
        dossier = _dossier_for(shot)
        return (
            dbc.Alert(
                [
                    html.Strong(f"Opened SHOT/{shot}"),
                    html.Span(f" · status={st}"),
                    html.Div(
                        "Tabs: Overview · Level-2 · Residuals · Planner · Compare · EFIT · GSFit · Equilibria · Authorities · Files.",
                        className="small mt-1",
                    ),
                ],
                color="info",
                duration=4200,
            ),
            shot,
            "idle" if not manager.is_running else no_update,
            manager.is_running,
            str(int(shot)),
            rd.as_posix(),
            dossier,
        )

    @app.callback(
        Output("run-alert", "children"),
        Output("active-shot", "data"),
        Output("ui-status", "data"),
        Output("btn-start", "disabled"),
        Output("shot-input", "value"),
        Output("shot-path", "children"),
        Output("shot-dossier", "children"),
        Input("shot-picker", "value"),
        prevent_initial_call=True,
    )
    def on_picker(picker_val):
        if picker_val is None:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update
        return _open_shot(int(picker_val))

    @app.callback(
        Output("run-alert", "children", allow_duplicate=True),
        Output("active-shot", "data", allow_duplicate=True),
        Output("ui-status", "data", allow_duplicate=True),
        Output("btn-start", "disabled", allow_duplicate=True),
        Output("shot-input", "value", allow_duplicate=True),
        Output("shot-path", "children", allow_duplicate=True),
        Output("shot-dossier", "children", allow_duplicate=True),
        Output("refresh-token", "data", allow_duplicate=True),
        Input("btn-open", "n_clicks"),
        Input("btn-start", "n_clicks"),
        Input("btn-cancel", "n_clicks"),
        Input("shot-input", "n_submit"),
        State("shot-input", "value"),
        State("shot-picker", "value"),
        State("active-shot", "data"),
        State("ui-status", "data"),
        State("refresh-token", "data"),
        prevent_initial_call=True,
    )
    def on_buttons(n_open, n_start, n_cancel, n_submit, shot_val, picker_val, active_shot, ui_status, refresh_token):
        ctx = dash.callback_context
        if not ctx.triggered:
            return (no_update,) * 8
        tid = ctx.triggered[0]["prop_id"].split(".")[0]
        tok = int(refresh_token or 0)

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
                    _dossier_for(active_shot) if active_shot is not None else no_update,
                    tok + 1,
                )
            return (
                dbc.Alert("Nothing to cancel.", color="secondary", duration=2200),
                active_shot,
                ui_status,
                False,
                no_update,
                no_update,
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
                no_update,
                no_update,
            )

        if tid in {"btn-open", "shot-input"}:
            opened = _open_shot(shot)
            return (*opened, tok + 1)

        if tid != "btn-start":
            return (no_update,) * 8

        if manager.is_running:
            return (
                dbc.Alert("A run is already in progress.", color="warning", duration=3000),
                active_shot,
                "running",
                True,
                str(int(shot)),
                no_update,
                _dossier_for(active_shot) if active_shot is not None else no_update,
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
                str(int(shot)),
                no_update,
                no_update,
                no_update,
            )
        rd = art.run_dir_for(runs_dir, shot)
        return (
            dbc.Alert(
                [
                    html.Strong(f"Reconstructing shot {shot}"),
                    html.Div(
                        "Prior results are archived under history/. Watch Stages — tabs refresh now and when the run finishes. Cached Level-2 Zarrs are reused when verified.",
                        className="small mt-1",
                    ),
                ],
                color="primary",
                duration=4500,
            ),
            shot,
            "running",
            True,
            str(int(shot)),
            rd.as_posix(),
            _dossier_for(shot),
            tok + 1,
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
        Output("shot-dossier", "children", allow_duplicate=True),
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
        # While a subprocess is live, bind progress to that shot — not a differently Open'd shot.
        if running and snap.get("shot") is not None:
            shot = snap.get("shot")
        else:
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
        elif snap.get("cancelled") or (snap.get("returncode") == -1 and ui_status in {"running", "cancelled"}):
            status_label = "cancelled"
            if ui_status != "cancelled":
                bump = int(refresh_token or 0) + 1
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
            st = str(progress.get("status") or "")
            # Never trust disk "running"/"started" without a live process.
            if st in {"success", "failed"}:
                status_label = st
            elif st in {"running", "started"}:
                if ui_status == "cancelled":
                    status_label = "cancelled"
                elif man and man.get("status") in {"success", "failed"}:
                    status_label = str(man.get("status"))
                else:
                    status_label = "interrupted"
            elif st:
                status_label = st
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
                new_lib_fp = _library_fingerprint(runs_dir, cache_dir=cache_dir)
            except OSError:
                new_lib_fp = library_fp
            if new_lib_fp != library_fp:
                out_opts = _cached_shot_library_options(
                    runs_dir,
                    cache_dir=cache_dir,
                    required_groups=required_groups,
                    library_fp=new_lib_fp,
                )
            lib_check = 0
        else:
            lib_check = int(cache.get("lib_check") or 0) + 1

        out_zip_href = zip_href if cache.get("zip_href") != zip_href else no_update
        out_zip_cls = zip_cls if cache.get("zip_cls") != zip_cls else no_update
        out_path = path_txt if cache.get("path") != path_txt else no_update
        out_lib_fp = new_lib_fp if new_lib_fp != library_fp else no_update

        dossier_sig = (
            f"{shot}|{status_label}|{stage_sig}|{refresh_token}|"
            f"{art.results_fingerprint(run_dir) if run_dir else ''}"
        )
        if cache.get("dossier_sig") != dossier_sig:
            out_dossier = _dossier_for(int(shot)) if shot is not None else panels.shot_dossier(None, None)
        else:
            out_dossier = no_update

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
            "dossier_sig": dossier_sig,
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
            out_dossier,
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
        State("compare-shot-a", "data"),
        State("compare-shot-b", "data"),
        State("compare-family-store", "data"),
        prevent_initial_call=False,
    )
    def on_results(active_shot, active_tab, _refresh_token, _n_refresh, cmp_a, cmp_b, cmp_fam):
        """Fill the active tab. Shot changes always rebuild Overview (even if tab value is unchanged)."""
        triggered = None
        try:
            triggered = dash.callback_context.triggered_id
        except Exception:
            triggered = None

        tid = (active_tab or "overview").strip().lower()
        # Opening / switching shot must refresh body even when already on Overview.
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

        # Cache heavy tab bodies (Compare / Planner / EFIT) so switching back is instant.
        # Key includes results fingerprint + refresh token so rebuilds stay honest.
        refresh_sig = str(_refresh_token or "")
        if tid == "compare":
            lib_fp_now = _library_fingerprint(runs_dir, cache_dir=cache_dir)
            try:
                shot_a = int(cmp_a) if cmp_a is not None else None
            except (TypeError, ValueError):
                shot_a = None
            try:
                shot_b = int(cmp_b) if cmp_b is not None else None
            except (TypeError, ValueError):
                shot_b = None
            fam = str(cmp_fam or "plasma")
            lib_shots = art.list_shot_dirs(runs_dir)
            def_a, def_b = panels.default_compare_pair(shot_i, lib_shots)
            if shot_a is None:
                shot_a = def_a
            if shot_b is None:
                shot_b = def_b
            fp_a = art.results_fingerprint(art.run_dir_for(runs_dir, shot_a)) if shot_a else ""
            fp_b = art.results_fingerprint(art.run_dir_for(runs_dir, shot_b)) if shot_b else ""
            cache_key = f"compare|{shot_a}|{shot_b}|{fam}|{fp_a}|{fp_b}|{lib_fp_now}|{refresh_sig}"
            cached = _tab_body_cache_get(cache_key)
            if cached is not None:
                return heading, cached
            lib_opts = _cached_shot_library_options(
                runs_dir,
                cache_dir=cache_dir,
                required_groups=required_groups,
                library_fp=lib_fp_now,
            )
            body = panels.compare_panel(
                runs_dir,
                library_options=lib_opts,
                shot_a=shot_a,
                shot_b=shot_b,
                family=fam,
            )
            _tab_body_cache_put(cache_key, body)
        else:
            fp = art.results_fingerprint(run_dir) if run_dir else ""
            cache_key = f"{tid}|{shot_i}|{fp}|{refresh_sig}"
            # Cache heavy tabs; Overview is cheap but still cached for snappy return.
            if tid in {"planner", "efit", "gsfit", "compare", "gifs", "residuals", "auth", "level2", "overview", "files"}:
                cached = _tab_body_cache_get(cache_key)
                if cached is not None:
                    return heading, cached
            body = panels.fill_one_tab(tid, shot_i, run_dir, repo_root=repo_root)
            if tid in {"planner", "efit", "gsfit", "gifs", "residuals", "auth", "level2", "overview", "files"}:
                _tab_body_cache_put(cache_key, body)
        return heading, body

    @app.callback(
        Output("compare-detail", "children"),
        Output("compare-shot-a", "data"),
        Output("compare-shot-b", "data"),
        Output("compare-family-store", "data"),
        Input("compare-dd-a", "value"),
        Input("compare-dd-b", "value"),
        Input("compare-family", "value"),
        prevent_initial_call=True,
    )
    def on_compare(shot_a, shot_b, family):
        """Update Compare detail when A/B/family pickers change."""
        try:
            a = int(shot_a) if shot_a is not None and str(shot_a).strip() != "" else None
        except (TypeError, ValueError):
            a = None
        try:
            b = int(shot_b) if shot_b is not None and str(shot_b).strip() != "" else None
        except (TypeError, ValueError):
            b = None
        fam = str(family or "plasma")
        return panels.compare_detail(runs_dir, a, b, fam), a, b, fam

    @app.callback(
        Output("compare-dd-a", "value", allow_duplicate=True),
        Output("compare-dd-b", "value", allow_duplicate=True),
        Input("compare-btn-swap", "n_clicks"),
        State("compare-dd-a", "value"),
        State("compare-dd-b", "value"),
        prevent_initial_call=True,
    )
    def on_compare_swap(n_clicks, shot_a, shot_b):
        """Swap Shot A ↔ Shot B (dropdown values; on_compare refreshes detail)."""
        if not n_clicks:
            return no_update, no_update
        return shot_b, shot_a

    @app.callback(
        Output("planner-edit-status", "children"),
        Output("refresh-token", "data", allow_duplicate=True),
        Input("planner-btn-save", "n_clicks"),
        Input("planner-btn-replan", "n_clicks"),
        State({"type": "planner-r", "circuit": ALL}, "value"),
        State({"type": "planner-r", "circuit": ALL}, "id"),
        State({"type": "planner-l", "circuit": ALL}, "value"),
        State({"type": "planner-l", "circuit": ALL}, "id"),
        State("planner-rl-citation", "value"),
        State("planner-passive-json", "value"),
        State("active-shot", "data"),
        State("refresh-token", "data"),
        prevent_initial_call=True,
    )
    def on_planner_edit(
        n_save,
        n_replan,
        r_vals,
        r_ids,
        l_vals,
        l_ids,
        citation,
        passive_json,
        active_shot,
        refresh_token,
    ):
        """Save R/L + passive ρ to configs/; optionally re-run planner-only."""
        ctx = dash.callback_context
        if not ctx.triggered:
            return no_update, no_update
        trig = str(ctx.triggered[0]["prop_id"])
        try:
            from mast_freegsnke.planner_replan import (
                PlannerReplanError,
                apply_circuit_rl_edits,
                apply_passive_resistivity_edits,
            )
        except Exception as e:
            return f"Import error: {e}", no_update

        edits: dict = {}
        for vid, val in zip(r_ids or [], r_vals or []):
            if not isinstance(vid, dict):
                continue
            name = str(vid.get("circuit") or "")
            if not name:
                continue
            edits.setdefault(name, {})
            if val is not None and str(val).strip() != "":
                try:
                    edits[name]["R_ohm"] = float(val)
                except (TypeError, ValueError):
                    return f"Invalid R_ohm for {name}", no_update
        for vid, val in zip(l_ids or [], l_vals or []):
            if not isinstance(vid, dict):
                continue
            name = str(vid.get("circuit") or "")
            if not name:
                continue
            edits.setdefault(name, {})
            if val is not None and str(val).strip() != "":
                try:
                    edits[name]["L_henry"] = float(val)
                except (TypeError, ValueError):
                    return f"Invalid L_henry for {name}", no_update

        msgs = []
        try:
            if edits:
                apply_circuit_rl_edits(
                    repo_root,
                    edits,
                    citation_note=str(citation).strip() if citation else None,
                )
                msgs.append(f"Saved R/L for {len(edits)} circuit(s).")
            # Passives: empty object clears to awaiting
            import json as _json

            raw = (passive_json or "").strip()
            if raw:
                comps = _json.loads(raw)
                if not isinstance(comps, dict):
                    return "Passive JSON must be an object of components", no_update
                apply_passive_resistivity_edits(repo_root, comps)
                msgs.append(
                    f"Passive resistivity: {len(comps)} component(s) "
                    f"({'cited' if comps else 'awaiting_authority'})."
                )
            else:
                msgs.append("Passive rho unchanged (empty editor — not wiped).")
        except PlannerReplanError as e:
            return f"Save failed: {e}", no_update
        except Exception as e:
            return f"Save failed: {e}", no_update

        if "planner-btn-replan" in trig:
            if active_shot is None:
                return " ".join(msgs) + " Open a shot before re-calculate.", no_update
            try:
                shot_i = int(active_shot)
            except (TypeError, ValueError):
                return " ".join(msgs) + " Invalid active shot.", no_update
            try:
                manager.start_plan(shot_i, config=config_path, cwd=repo_root)
            except Exception as e:
                return " ".join(msgs) + f" Replan start failed: {e}", no_update
            msgs.append(f"Planner re-calculate started for SHOT/{shot_i}.")
            tok = int(refresh_token or 0) + 1
            return " ".join(msgs), tok

        return " ".join(msgs) or "Nothing to save.", no_update

    @app.callback(
        Output("files-table", "children"),
        Input("files-filter", "value"),
        State("active-shot", "data"),
        prevent_initial_call=True,
    )
    def on_files_filter(query, active_shot):
        if active_shot is None:
            return no_update
        try:
            shot_i = int(active_shot)
        except (TypeError, ValueError):
            return no_update
        rd = art.run_dir_for(runs_dir, shot_i)
        if not rd.is_dir():
            return no_update
        return panels.downloads_table(shot_i, rd, query=str(query or ""))

    @app.callback(
        Output("compare-shot-a", "data", allow_duplicate=True),
        Output("compare-shot-b", "data", allow_duplicate=True),
        Input("results-tabs", "value"),
        State("active-shot", "data"),
        State("compare-shot-a", "data"),
        State("compare-shot-b", "data"),
        prevent_initial_call=True,
    )
    def seed_compare_defaults(tab, active_shot, cmp_a, cmp_b):
        """Persist default A/B when opening Compare with empty stores."""
        if (tab or "").strip().lower() != "compare":
            return no_update, no_update
        if cmp_a is not None and cmp_b is not None:
            return no_update, no_update
        lib_shots = art.list_shot_dirs(runs_dir)
        try:
            active_i = int(active_shot) if active_shot is not None else None
        except (TypeError, ValueError):
            active_i = None
        def_a, def_b = panels.default_compare_pair(active_i, lib_shots)
        out_a = cmp_a if cmp_a is not None else def_a
        out_b = cmp_b if cmp_b is not None else def_b
        if out_a is None and out_b is None:
            return no_update, no_update
        return out_a, out_b

    @app.callback(
        Output("l2-detail", "children"),
        Input("l2-family", "value"),
        State("active-shot", "data"),
        prevent_initial_call=True,
    )
    def on_l2_family(family_key, active_shot):
        """Load one Level-2 family on demand (keeps tab switches smooth)."""
        if active_shot is None or not family_key:
            return no_update
        try:
            shot_i = int(active_shot)
        except (TypeError, ValueError):
            return no_update
        run_dir = art.run_dir_for(runs_dir, shot_i)
        if not run_dir.is_dir():
            return html.P("Shot folder missing.", className="text-muted small")
        return panels.level2_family_detail(shot_i, run_dir, str(family_key))

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
    import sys

    print("[ui] Building Dash app…", flush=True)
    app = create_app(repo_root=repo_root, runs_dir=runs_dir, config_path=config_path)
    url = f"http://{host}:{port}"
    lib = (Path(runs_dir) if Path(runs_dir).is_absolute() else (Path(repo_root) / runs_dir)).resolve()
    print(f"[ui] Shot-only Dash UI → {url}", flush=True)
    print(f"[ui] Library: {lib}", flush=True)
    print("[ui] Leave this window open. Press Ctrl+C to stop.", flush=True)
    should_open = bool(open_browser) and (not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true")
    if should_open:
        _open_browser(url)
        print("[ui] Opening browser… (--no-browser to skip)", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    app.run(host=host, port=int(port), debug=bool(debug))
