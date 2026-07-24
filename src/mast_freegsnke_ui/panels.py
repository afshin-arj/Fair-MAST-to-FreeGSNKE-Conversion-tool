"""Dash panel builders for the shot results browser."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from mast_freegsnke_ui import artifacts as art

_MAX_RESIDUAL_CHARTS = 3
_MAX_PLOT_POINTS = 400
_MAX_GALLERY = 8
_MAX_CSV_PREVIEW = 2
_MAX_SUMMARY_CHARS = 5000
_MAX_GIFS = 4


def _require() -> tuple[Any, Any, Any]:
    from dash import dcc, html
    import dash_bootstrap_components as dbc

    return html, dcc, dbc


def _fmt_kpi(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if abs(value) >= 1e4 or (abs(value) > 0 and abs(value) < 1e-2):
            return f"{value:.3g}"
        return f"{value:.4g}"
    return str(value)


def empty_state(title: str, body: str, *, steps: Optional[List[str]] = None) -> Any:
    html, _, dbc = _require()
    kids: List[Any] = [
        html.Div("No shot context", className="empty-kicker"),
        html.H5(title, className="empty-title"),
        html.P(body, className="empty-body mb-0"),
    ]
    if steps:
        kids.append(
            html.Ol(
                [html.Li(s) for s in steps],
                className="empty-steps",
            )
        )
    return html.Div(kids, className="empty-state")


def tab_banner(title: str, note: str) -> Any:
    html, _, _ = _require()
    return html.Div(
        [
            html.H6(title, className="tab-banner-title"),
            html.P(note, className="tab-banner-note"),
        ],
        className="tab-banner",
    )


def chip(label: str, value: Any, *, tone: str = "") -> Any:
    html, _, _ = _require()
    cls = "fg-chip" + (f" fg-chip-{tone}" if tone else "")
    return html.Span(
        [html.Span(str(label), className="fg-chip-k"), html.Span(_fmt_kpi(value), className="fg-chip-v")],
        className=cls,
    )


def shot_dossier(
    shot: Optional[int],
    run_dir: Optional[Path],
    *,
    cache_ready: Optional[bool] = None,
    cache_note: str = "",
) -> Any:
    """Compact science context strip for fusion experts."""
    html, _, _ = _require()
    if shot is None or run_dir is None or not Path(run_dir).is_dir():
        return html.Div(
            [
                html.Span("No active shot", className="dossier-empty"),
                html.Span("Open a library entry or Start a reconstruction", className="dossier-hint"),
            ],
            className="shot-dossier shot-dossier-empty",
        )
    k = art.overview_kpis(run_dir)
    st = str(k.get("status") or "?").lower()
    tone = "ok" if st in {"success", "ok", "completed"} else ("fail" if st in {"failed", "error"} else "warn")
    window = "—"
    if k.get("t_start") is not None or k.get("t_end") is not None:
        window = f"{_fmt_kpi(k.get('t_start'))} → {_fmt_kpi(k.get('t_end'))} s"
    modes = k.get("modes") or {}
    mode_txt = " · ".join(f"{a}={b}" for a, b in list(modes.items())[:4]) if modes else "—"
    cache_tone = ""
    cache_val = "—"
    if cache_ready is True:
        cache_val, cache_tone = "ready", "ok"
    elif cache_ready is False:
        cache_val, cache_tone = "partial/empty", "warn"
    chips = [
        chip("Shot", int(shot)),
        chip("Status", k.get("status"), tone=tone),
        chip("Window", window),
        chip("Modes", mode_txt),
        chip("Contracts", k.get("n_scored")),
        chip("EFIT", k.get("efit_ok")),
        chip("Evol. Ip", k.get("evolutive_ok")),
        chip("L2 cache", cache_val, tone=cache_tone),
    ]
    if k.get("blocking_n"):
        chips.append(chip("Blocking", k.get("blocking_n"), tone="fail"))
    return html.Div(
        [
            html.Div(chips, className="dossier-chips"),
            html.Div(cache_note, className="dossier-note") if cache_note else None,
        ],
        className="shot-dossier",
    )


def quick_links(shot: int, run_dir: Path) -> Any:
    """One-click access to the files experts open first."""
    html, _, _ = _require()
    links = []
    for rel, label in (
        ("01_summary/SUMMARY.md", "SUMMARY"),
        ("manifest.json", "manifest"),
        ("03_reconstruction/metrics/reconstruction_metrics.json", "metrics"),
        ("04_efit_compare/COMPARE.json", "COMPARE"),
        ("02_measured_data/00_index/catalog.json", "L2 catalog"),
        ("02_measured_data/00_index/optional_diagnostics.json", "optional L2"),
    ):
        if art.safe_resolve_under(run_dir, rel):
            links.append(
                html.A(label, href=art.file_url(shot, rel), target="_blank", className="fg-quick-link")
            )
    if not links:
        return None
    return html.Div(
        [html.Span("Open", className="fg-quick-label"), html.Div(links, className="fg-quick-links")],
        className="fg-quick-bar mb-3",
    )


def accordion(sections: List[tuple[str, Any, bool]], *, always_open: bool = True) -> Any:
    """Click-to-expand expert subsections — all start collapsed."""
    html, _, dbc = _require()
    items = []
    for i, (title, body, _start_open) in enumerate(sections):
        if body is None:
            continue
        items.append(
            dbc.AccordionItem(
                html.Div(body, className="accordion-body-pad"),
                title=title,
                item_id=f"sec-{i}",
            )
        )
    if not items:
        return html.Div()
    return dbc.Accordion(
        items,
        always_open=always_open,
        start_collapsed=True,
        active_item=[] if always_open else None,
        class_name="fg-accordion",
    )


def kpi_strip(kpis: Dict[str, Any]) -> Any:
    html, _, dbc = _require()

    def cell(label: str, value: Any, hint: str = "", tone: str = "") -> Any:
        cls = "kpi-cell" + (f" kpi-{tone}" if tone else "")
        return dbc.Col(
            html.Div(
                [
                    html.Div(label, className="kpi-label"),
                    html.Div(_fmt_kpi(value), className="kpi-value"),
                    html.Div(hint, className="kpi-hint") if hint else None,
                ],
                className=cls,
            ),
            xs=6,
            md=4,
            lg=2,
        )

    status = str(kpis.get("status") or "unknown")
    st = status.lower()
    tone = "ok" if st in {"success", "ok", "completed"} else ("fail" if st in {"failed", "error"} else "")
    window = "—"
    if kpis.get("t_start") is not None or kpis.get("t_end") is not None:
        window = f"{kpis.get('t_start')} → {kpis.get('t_end')} s"
    rms = kpis.get("evolutive_rms_A")
    rms_hint = f"rms={_fmt_kpi(rms)} A" if rms is not None else ""

    return dbc.Row(
        [
            cell("Status", status, tone=tone),
            cell("Window", window),
            cell("Contracts", kpis.get("n_scored"), f"ok={_fmt_kpi(kpis.get('metrics_ok'))}"),
            cell("EFIT archive", kpis.get("efit_ok")),
            cell("Evolutive Ip", kpis.get("evolutive_ok"), rms_hint),
            cell("Blocking", kpis.get("blocking_n"), tone="fail" if (kpis.get("blocking_n") or 0) else ""),
        ],
        className="kpi-row g-2 mb-3",
    )


def stage_progress_bar(progress: Optional[Dict[str, Any]], running: bool) -> Any:
    html, _, dbc = _require()
    if not progress:
        return html.Div(className="stage-progress-wrap")
    stages = [s for s in (progress.get("stage_log") or []) if isinstance(s, dict)]
    if not stages and not running:
        return html.Div(className="stage-progress-wrap")
    n = max(len(stages), 1)
    done = sum(1 for s in stages if s.get("ok"))
    failed = any(not s.get("ok") for s in stages)
    pct = int(round(100 * done / n)) if stages else (8 if running else 0)
    if running and stages:
        pct = min(95, max(pct, int(round(100 * (done + 0.35) / max(n + 1, 1)))))
    color = "danger" if failed and not running else ("success" if not running and done == n and n else "info")
    label = f"{done}/{n} stages" + (" · running" if running else "")
    return html.Div(
        [
            html.Div(
                [html.Span(label, className="stage-progress-label"), html.Span(f"{pct}%", className="stage-progress-pct")],
                className="d-flex justify-content-between mb-1",
            ),
            dbc.Progress(value=pct, color=color, className="stage-progress", style={"height": "6px"}),
        ],
        className="stage-progress-wrap mb-2",
    )


def stage_timeline(progress: Optional[Dict[str, Any]], running: bool) -> Any:
    html, _, dbc = _require()
    if not progress:
        return html.P(
            "Waiting for a run — enter a shot and press Start, or open one from the library.",
            className="text-muted small mb-0",
        )
    stages = progress.get("stage_log") or []
    current = progress.get("current_stage")
    items = []
    for st in stages:
        if not isinstance(st, dict):
            continue
        name = st.get("stage") or "?"
        ok = bool(st.get("ok"))
        err = st.get("error")
        is_current = name == current and running
        cls = "stage-item"
        if is_current:
            cls += " stage-active"
        elif ok:
            cls += " stage-ok"
        else:
            cls += " stage-fail"
        badge = "RUN" if is_current else ("OK" if ok else "FAIL")
        note = st.get("note")
        hits = st.get("cache_hits")
        synced = st.get("synced")
        detail_bits: List[str] = []
        if note:
            detail_bits.append(str(note))
        if isinstance(hits, list) and hits:
            detail_bits.append(f"cache {len(hits)}")
        if isinstance(synced, list) and synced:
            detail_bits.append(f"sync {len(synced)}")
        elif isinstance(synced, list) and note and "local_cache" in str(note):
            detail_bits.append("no S3 sync")
        detail = " · ".join(detail_bits)[:140] if detail_bits else None
        body: List[Any] = [
            html.Span(badge, className="stage-badge"),
            html.Span(
                [
                    html.Span(str(name), className="stage-name"),
                    html.Span(detail, className="stage-note") if detail and ok else None,
                    html.Span(str(err)[:120], className="stage-err") if err and not ok else None,
                ]
            ),
        ]
        items.append(html.Li(body, className=cls))
    if not items:
        return html.P("Waiting for first stage…", className="text-muted small mb-0")
    return html.Ul(items, className="stage-list mb-0")


def media_card(shot: int, path: Path, run_dir: Path) -> Any:
    html, _, dbc = _require()
    rel = art.rel_posix(path, run_dir)
    view = art.file_url_for_path(shot, path, run_dir, download=False)
    dl = art.file_url_for_path(shot, path, run_dir, download=True)
    is_gif = path.suffix.lower() == ".gif"
    # Verify the URL path is servable; if not, fall back to data URI for small images.
    img_src = view
    if art.safe_resolve_under(run_dir, rel) is None:
        try:
            small = Path(path).stat().st_size < 2_500_000
        except OSError:
            small = False
        if small:
            uri = art.file_to_data_uri(path)
            if uri:
                img_src = uri
    return html.Div(
        [
            html.Div(
                html.Img(
                    src=img_src,
                    alt=Path(rel).name,
                    className="media-img",
                ),
                className="media-frame",
            ),
            html.Div(
                [
                    html.Div(Path(rel).name, className="media-basename", title=rel),
                    html.Div(rel, className="media-caption text-truncate", title=rel),
                    html.Div(
                        [
                            html.A("Open", href=view, target="_blank", className="btn btn-sm btn-outline-secondary me-1"),
                            html.A("Download", href=dl, className="btn btn-sm btn-primary"),
                        ],
                        className="media-actions",
                    ),
                ],
                className="media-meta",
            ),
        ],
        className="media-card" + (" media-gif" if is_gif else ""),
    )


def media_gallery(shot: int, paths: List[Path], run_dir: Path, empty: str) -> Any:
    html, _, dbc = _require()
    if not paths:
        return html.P(empty, className="text-muted")
    shown = paths[:_MAX_GALLERY]
    cols = [dbc.Col(media_card(shot, p, run_dir), xs=12, md=6, xl=4) for p in shown]
    extra = ""
    if len(paths) > _MAX_GALLERY:
        extra = html.P(
            f"Showing {_MAX_GALLERY} of {len(paths)} — download the ZIP for the full set.",
            className="small text-muted mt-2 mb-0",
        )
    return html.Div([dbc.Row(cols, className="g-3"), extra])


def export_bar(shot: int, run_dir: Path) -> Any:
    html, _, dbc = _require()
    # Quick catalog only — never walk the full SHOT tree on Overview.
    quick_items = art.catalog_quick(run_dir)
    zip_href = f"/shot-zip/{int(shot)}"
    quick = []
    for rel, label in (
        ("01_summary/SUMMARY.md", "SUMMARY.md"),
        ("01_summary/SUMMARY.json", "SUMMARY.json"),
        ("manifest.json", "manifest.json"),
        ("03_reconstruction/metrics/reconstruction_metrics.json", "metrics.json"),
        ("04_efit_compare/COMPARE.json", "COMPARE.json"),
    ):
        if art.safe_resolve_under(run_dir, rel):
            quick.append(
                html.A(
                    label,
                    href=art.file_url(shot, rel, download=True),
                    className="btn btn-sm btn-outline-secondary me-1 mb-1",
                )
            )
    return html.Div(
        [
            html.Div(
                [
                    html.Span(f"{len(quick_items)} key files", className="text-muted small me-2"),
                    html.A(
                        "Download ZIP",
                        href=zip_href,
                        className="btn btn-sm btn-success",
                    ),
                ],
                className="d-flex flex-wrap align-items-center mb-2 gap-1",
            ),
            html.Div(quick, className="export-quick"),
        ],
        className="export-bar mb-3",
    )


def downloads_table(shot: int, run_dir: Path) -> Any:
    html, _, dbc = _require()
    rows = []
    for item in art.catalog_downloadables(run_dir)[:200]:
        rel = item["rel"]
        rows.append(
            html.Tr(
                [
                    html.Td(item["group"]),
                    html.Td(item["kind"]),
                    html.Td(html.Code(rel, className="small")),
                    html.Td(f"{item['bytes']:,}"),
                    html.Td(
                        [
                            html.A("View", href=art.file_url(shot, rel), target="_blank", className="me-2"),
                            html.A("Download", href=art.file_url(shot, rel, download=True)),
                        ]
                    ),
                ]
            )
        )
    if not rows:
        return html.P("No downloadable artifacts yet.", className="text-muted")
    return dbc.Table(
        [
            html.Thead(html.Tr([html.Th(h) for h in ("Group", "Type", "Path", "Bytes", "Actions")])),
            html.Tbody(rows),
        ],
        bordered=False,
        hover=True,
        size="sm",
        responsive=True,
        className="downloads-table",
    )


def overview_panel(shot: int, run_dir: Path) -> Any:
    html, dcc, dbc = _require()
    kpis = art.overview_kpis(run_dir)
    md = art.load_summary_markdown(run_dir)
    blocking = kpis.get("blocking") or []
    # Compact SUMMARY: excerpt + download — avoid huge Markdown DOM (theme H1s + lag).
    summary_body: Any
    if md:
        excerpt = md.strip()
        truncated = len(excerpt) > _MAX_SUMMARY_CHARS
        if truncated:
            excerpt = excerpt[:_MAX_SUMMARY_CHARS].rstrip() + "\n\n… truncated in UI — open SUMMARY.md for the full write-up."
        # Soften heading levels so browser theme H1/H2 do not dominate
        soft_lines = []
        for line in excerpt.splitlines():
            if line.startswith("# "):
                soft_lines.append("### " + line[2:])
            elif line.startswith("## "):
                soft_lines.append("#### " + line[3:])
            else:
                soft_lines.append(line)
        soft_md = "\n".join(soft_lines)
        summary_body = html.Div(
            [
                dcc.Markdown(soft_md, className="summary-md", dangerously_allow_html=False),
                html.Div(
                    [
                        html.A(
                            "Open SUMMARY.md",
                            href=art.file_url(shot, "01_summary/SUMMARY.md"),
                            target="_blank",
                            className="btn btn-sm btn-outline-secondary me-1",
                        ),
                        html.A(
                            "Download",
                            href=art.file_url(shot, "01_summary/SUMMARY.md", download=True),
                            className="btn btn-sm btn-outline-secondary",
                        ),
                    ],
                    className="mt-2",
                )
                if art.safe_resolve_under(run_dir, "01_summary/SUMMARY.md")
                else None,
            ],
            className="summary-wrap",
        )
    else:
        summary_body = html.Pre(art.overview_text(run_dir), className="overview-pre")
    blocking_body = None
    if blocking:
        blocking_body = dbc.Alert(
            [html.Strong("Fail-fast — do not invent metrology."), html.Ul([html.Li(str(b)) for b in blocking], className="mb-0 mt-2")] ,
            color="danger",
        )
    return html.Div(
        [
            tab_banner(
                "Science overview",
                "Status, formed-plasma window, and SUMMARY for this reconstruction. "
                "Expand a section only when you need detail.",
            ),
            quick_links(shot, run_dir),
            accordion(
                [
                    ("Key performance indicators", kpi_strip(kpis), False),
                    ("Blocking errors", blocking_body, False),
                    ("Downloads", export_bar(shot, run_dir), False),
                    ("SUMMARY.md", summary_body, False),
                ]
            ),
        ]
    )


def _downsample_df(df: Any, max_points: int = _MAX_PLOT_POINTS) -> Any:
    n = len(df)
    if n <= max_points:
        return df
    step = max(1, n // max_points)
    return df.iloc[::step].copy()


def residuals_panel(shot: int, run_dir: Path) -> Any:
    html, dcc, dbc = _require()
    metrics = art.load_metrics(run_dir)
    rows = art.metrics_table_rows(metrics)
    table_body: Any = None
    charts_body: List[Any] = []
    if metrics:
        table_body = [
            html.P(
                f"ok={metrics.get('ok')} · n_scored={metrics.get('n_scored')} · "
                f"n_skipped_all_nan={metrics.get('n_skipped_all_nan')}",
                className="small text-muted",
            )
        ]
    else:
        table_body = []
    if rows:
        header = html.Tr([html.Th(c) for c in ("contract", "rms", "mae", "max_abs", "n")])
        body = [
            html.Tr(
                [
                    html.Td(r["contract"]),
                    html.Td(_fmt(r["rms"])),
                    html.Td(_fmt(r["mae"])),
                    html.Td(_fmt(r["max_abs"])),
                    html.Td(r["n"]),
                ]
            )
            for r in rows
        ]
        table_body.append(
            dbc.Table(
                [html.Thead(header), html.Tbody(body)],
                bordered=False,
                hover=True,
                size="sm",
                responsive=True,
            )
        )
        csv_links = []
        for csv_path in art.residual_csv_paths(run_dir):
            rel = art.rel_posix(csv_path, run_dir)
            csv_links.append(
                html.A(
                    csv_path.name,
                    href=art.file_url(shot, rel, download=True),
                    className="btn btn-sm btn-outline-secondary me-1 mb-1",
                )
            )
        if csv_links:
            table_body.append(html.Div([html.Span("CSV: ", className="small text-muted")] + csv_links))

    try:
        import pandas as pd
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        pd = None  # type: ignore
        go = None  # type: ignore
        make_subplots = None  # type: ignore

    csvs = art.residual_csv_paths(run_dir)
    if pd is not None and go is not None and csvs:
        plot_cfg = {
            "displaylogo": False,
            "responsive": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            "toImageButtonOptions": {"format": "png"},
        }
        for csv_path in csvs[:_MAX_RESIDUAL_CHARTS]:
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            if "time" not in df.columns:
                continue
            df = _downsample_df(df)
            layout_kw = dict(
                height=360,
                margin=dict(l=48, r=20, t=40, b=36),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(11,16,23,0.45)",
                font=dict(size=11),
                uirevision=csv_path.name,
            )
            if "exp" in df.columns and "syn" in df.columns and make_subplots is not None:
                fig = make_subplots(
                    rows=2,
                    cols=1,
                    shared_xaxes=True,
                    subplot_titles=("exp vs syn", "residual"),
                    vertical_spacing=0.1,
                )
                fig.add_trace(
                    go.Scattergl(x=df["time"], y=df["exp"], name="exp", mode="lines", line=dict(width=1.4)),
                    row=1,
                    col=1,
                )
                fig.add_trace(
                    go.Scattergl(x=df["time"], y=df["syn"], name="syn", mode="lines", line=dict(width=1.4)),
                    row=1,
                    col=1,
                )
                if "residual" in df.columns:
                    fig.add_trace(
                        go.Scattergl(
                            x=df["time"],
                            y=df["residual"],
                            name="residual",
                            mode="lines",
                            line=dict(width=1.2, color="#c45c26"),
                        ),
                        row=2,
                        col=1,
                    )
                fig.update_layout(title_text=csv_path.name, **layout_kw)
            else:
                fig = go.Figure()
                ycol = "residual" if "residual" in df.columns else df.columns[1]
                fig.add_trace(go.Scattergl(x=df["time"], y=df[ycol], name=ycol, mode="lines"))
                fig.update_layout(title=csv_path.name, **layout_kw)
            charts_body.append(dcc.Graph(figure=fig, config=plot_cfg, className="residual-graph"))
        if len(csvs) > _MAX_RESIDUAL_CHARTS:
            charts_body.append(
                html.P(
                    f"Showing {_MAX_RESIDUAL_CHARTS} of {len(csvs)} interactive charts — open CSVs or ZIP for the rest.",
                    className="small text-muted",
                )
            )

    pngs = media_gallery(shot, art.residual_plot_paths(run_dir), run_dir, "No residual PNGs under report/key_plots/.")
    if not table_body and not charts_body:
        return empty_state("No residuals yet", "Run the pipeline with contract metrics enabled.")
    return html.Div(
        [
            tab_banner(
                "Contract residuals",
                "FreeGSNKE synthetic vs experimental contracts. Expand charts only when you need them.",
            ),
            accordion(
                [
                    ("Metrics table & CSV", html.Div(table_body) if table_body else None, True),
                    ("Interactive traces", html.Div(charts_body) if charts_body else None, False),
                    ("Saved residual PNGs", pngs, False),
                ]
            ),
        ]
    )


def _fmt(v: Any) -> str:
    try:
        return f"{float(v):.4g}"
    except (TypeError, ValueError):
        return "—" if v is None else str(v)


def efit_panel(shot: int, run_dir: Path) -> Any:
    html, _, dbc = _require()
    efit = art.load_efit_compare(run_dir)
    score = art.load_shape_scorecard(run_dir)
    compare_body: Any = None
    score_body: Any = None
    if efit:
        keys = [k for k in ("ok", "n_times", "errors", "fix_hint", "label", "status") if k in efit]
        extra = [k for k in efit.keys() if k not in keys][:8]
        rows = []
        for k in keys + extra:
            val = efit.get(k)
            if isinstance(val, (list, dict)):
                val = str(val)[:240]
            rows.append(html.Tr([html.Td(html.Code(str(k))), html.Td(str(val))]))
        links = []
        for rel in ("04_efit_compare/COMPARE.json", "04_efit_compare/COMPARE.md", "04_efit_compare/shape_scorecard.csv"):
            if art.safe_resolve_under(run_dir, rel):
                links.append(
                    html.A(
                        f"Download {Path(rel).name}",
                        href=art.file_url(shot, rel, download=True),
                        className="btn btn-sm btn-outline-secondary me-1 mb-2",
                    )
                )
        compare_body = html.Div(
            [
                dbc.Table(
                    [html.Thead(html.Tr([html.Th("Field"), html.Th("Value")])), html.Tbody(rows)],
                    bordered=False,
                    size="sm",
                    responsive=True,
                ),
                html.Div(links),
            ]
        )
    if score and isinstance(score, dict):
        srows = [html.Tr([html.Td(str(k)), html.Td(str(v)[:200])]) for k, v in list(score.items())[:40]]
        score_body = dbc.Table(
            [html.Thead(html.Tr([html.Th("Metric"), html.Th("Value")])), html.Tbody(srows)],
            bordered=False,
            size="sm",
            responsive=True,
        )
    return html.Div(
        [
            tab_banner(
                "EFIT archive compare",
                "FreeGSNKE vs FAIR-MAST Level-2 EFIT++ archive (ADR-002) — not a live EFIT++ / efit-ai / Py-EFIT solve.",
            ),
            accordion(
                [
                    ("COMPARE.json fields", compare_body, True),
                    ("Shape scorecard", score_body, False),
                    (
                        "EFIT plots",
                        media_gallery(shot, art.efit_plot_paths(run_dir), run_dir, "No EFIT compare plots yet."),
                        False,
                    ),
                ]
            ),
        ]
    )


def _csv_section_block(shot: int, run_dir: Path, section: str, items: List[Dict[str, Any]]) -> Any:
    """CSV inventory + optional small previews for one Level-2 family."""
    html, _, dbc = _require()
    from mast_freegsnke_ui import level2 as l2

    rows = []
    previews: List[Any] = []
    for it in items:
        if it.get("section") != section:
            continue
        rel = it["rel"]
        cols = it.get("columns") or []
        col_txt = ", ".join(str(c) for c in cols[:8]) if cols else "—"
        rows.append(
            html.Tr(
                [
                    html.Td(it.get("family") or it.get("name")),
                    html.Td(html.Code(rel, className="small")),
                    html.Td(f"{int(it.get('bytes') or 0):,}"),
                    html.Td(it.get("n_rows_approx") if it.get("n_rows_approx") is not None else "—"),
                    html.Td(col_txt, className="small text-muted"),
                    html.Td(
                        [
                            html.A("View", href=art.file_url(shot, rel), target="_blank", className="me-2"),
                            html.A("Download", href=art.file_url(shot, rel, download=True)),
                        ]
                    ),
                ]
            )
        )
        path = art.safe_resolve_under(run_dir, rel)
        if (
            path is not None
            and int(it.get("bytes") or 0) <= 1_500_000
            and len(previews) < _MAX_CSV_PREVIEW
        ):
            preview = l2.csv_preview_rows(path)
            if preview:
                ph = html.Tr([html.Th(c) for c in preview[0].keys()])
                pb = [html.Tr([html.Td(str(v)[:48]) for v in row.values()]) for row in preview]
                previews.append(
                    html.Div(
                        [
                            html.Div(rel, className="media-caption"),
                            dbc.Table([html.Thead(ph), html.Tbody(pb)], bordered=False, size="sm", responsive=True),
                        ],
                        className="mb-3",
                    )
                )
    if not rows:
        return None
    return html.Div(
        [
            dbc.Table(
                [
                    html.Thead(
                        html.Tr([html.Th(h) for h in ("Family", "Path", "Bytes", "Rows≈", "Columns", "Actions")])
                    ),
                    html.Tbody(rows),
                ],
                bordered=False,
                hover=True,
                size="sm",
                responsive=True,
                className="mb-3",
            ),
            html.Div(previews) if previews else html.P(
                "Large CSVs are download-only (preview skipped above ~1.5 MB).",
                className="small text-muted mb-0",
            ),
        ]
    )


def level2_panel(shot: int, run_dir: Path) -> Any:
    """FAIR-MAST Level-2 measured pack: plots + CSVs in click-to-expand families."""
    html, _, dbc = _require()
    from mast_freegsnke_ui import level2 as l2

    catalog = l2.load_measured_catalog(run_dir)
    grouped = l2.measured_plots_grouped(run_dir)
    csvs = l2.measured_csv_inventory(run_dir)
    status = l2.level2_status_files(run_dir)
    if not catalog and not grouped and not csvs:
        return empty_state(
            "No Level-2 measured pack yet",
            "Run the pipeline with enable_experimental_data so 02_measured_data/ is built from the FAIR-MAST extract.",
        )

    def _plot_sec(key: str, title: str) -> Any:
        paths = grouped.get(key) or []
        if not paths:
            return None
        return media_gallery(shot, paths, run_dir, f"No {title} plots.")

    index_bits: List[Any] = []
    if catalog:
        fams = catalog.get("families") or {}
        index_bits.append(
            html.P(
                f"Shot {catalog.get('shot', shot)} · families={len(fams) if isinstance(fams, dict) else 0} · "
                f"plots={len(catalog.get('plots') or [])} · window={catalog.get('window_s')}",
                className="small text-muted",
            )
        )
        if catalog.get("warnings"):
            index_bits.append(
                html.Ul([html.Li(str(w)) for w in list(catalog.get("warnings") or [])[:8]], className="small")
            )
    else:
        index_bits.append(html.P("catalog.json not found — listing files from disk.", className="small text-muted"))

    l1 = status.get("l1") or {}
    l3 = status.get("l3") or {}
    opt = status.get("optional") or {}
    opt_groups = (opt.get("groups") or {}) if isinstance(opt, dict) else {}
    avail = [k for k, v in opt_groups.items() if isinstance(v, dict) and v.get("available")]
    missing = [k for k, v in opt_groups.items() if isinstance(v, dict) and not v.get("available")]
    if avail or missing:
        index_bits.append(
            html.Div(
                [
                    html.P(
                        f"Optional L2 diagnostics — available: {', '.join(avail) or 'none'} · "
                        f"missing (warn only): {', '.join(missing) or 'none'}",
                        className="small mb-1",
                    ),
                    html.A(
                        "optional_diagnostics.json",
                        href=art.file_url(shot, "02_measured_data/00_index/optional_diagnostics.json"),
                        target="_blank",
                        className="btn btn-sm btn-outline-secondary",
                    )
                    if art.safe_resolve_under(run_dir, "02_measured_data/00_index/optional_diagnostics.json")
                    else None,
                ],
                className="mb-2",
            )
        )

    meta_body = html.Div(
        [
            html.P(
                f"L1: {l1.get('status') or l1.get('ok') or 'see STATUS.json'} · "
                f"L3: {l3.get('status') or l3.get('ok') or 'see STATUS.json'}",
                className="small",
            ),
            html.Div(
                [
                    html.A(
                        "L1 STATUS.json",
                        href=art.file_url(shot, "02_measured_data/l1/STATUS.json"),
                        target="_blank",
                        className="btn btn-sm btn-outline-secondary me-1",
                    )
                    if art.safe_resolve_under(run_dir, "02_measured_data/l1/STATUS.json")
                    else None,
                    html.A(
                        "L3 STATUS.json",
                        href=art.file_url(shot, "02_measured_data/l3/STATUS.json"),
                        target="_blank",
                        className="btn btn-sm btn-outline-secondary me-1",
                    )
                    if art.safe_resolve_under(run_dir, "02_measured_data/l3/STATUS.json")
                    else None,
                    html.A(
                        "catalog.json",
                        href=art.file_url(shot, "02_measured_data/00_index/catalog.json"),
                        target="_blank",
                        className="btn btn-sm btn-outline-secondary",
                    )
                    if art.safe_resolve_under(run_dir, "02_measured_data/00_index/catalog.json")
                    else None,
                ]
            ),
        ]
    )

    def _fam(key: str, title: str) -> List[tuple]:
        return [
            (f"{title} — plots", _plot_sec(key, title), False),
            (f"{title} — CSV", _csv_section_block(shot, run_dir, key, csvs), False),
        ]

    sections: List[tuple] = [
        ("Index & availability", html.Div(index_bits), False),
        *_fam("plasma", "Plasma"),
        *_fam("pf", "PF coils"),
        *_fam("magnetics", "Magnetics"),
        *_fam("geometry", "Geometry"),
        *_fam("summary", "Summary profiles"),
        *_fam("pulse_schedule", "Pulse schedule"),
        *_fam("spectrometer", "Spectrometer (visible)"),
        *_fam("soft_x_rays", "Soft X-rays"),
        *_fam("thomson", "Thomson scattering"),
        *_fam("cxrs", "CXRS"),
        *_fam("gas", "Gas injection"),
        *_fam("equilibrium_l2", "Equilibrium L2 scalars"),
        ("L1 / L3 status", meta_body, False),
        (
            "All Level-2 plots (capped)",
            media_gallery(
                shot,
                art.measured_plot_paths(run_dir)[:_MAX_GALLERY],
                run_dir,
                "No plots under 05_plots/.",
            ),
            False,
        ),
    ]
    return html.Div(
        [
            tab_banner(
                "FAIR-MAST Level-2 measured data",
                "Plasma · PF · magnetics · geometry plus optional diagnostics "
                "(summary, Soft X-rays, Thomson, CXRS, gas, …). "
                "Missing optional groups are warnings only — expand a family for plots and CSV.",
            ),
            html.Div(
                [
                    html.Span("Families", className="fg-quick-label"),
                    html.Div(
                        [
                            html.Span(lab, className="fg-family-pill")
                            for lab, key in (
                                ("Plasma", "plasma"),
                                ("PF", "pf"),
                                ("Magnetics", "magnetics"),
                                ("Geometry", "geometry"),
                                ("Summary", "summary"),
                                ("SXR", "soft_x_rays"),
                                ("Thomson", "thomson"),
                                ("CXRS", "cxrs"),
                                ("Gas", "gas"),
                            )
                            if grouped.get(key) or any(i.get("section") == key for i in csvs)
                        ]
                        or [html.Span("Core pack only — optional diagnostics not exported yet", className="small text-muted")],
                        className="fg-family-pills",
                    ),
                ],
                className="fg-quick-bar mb-3",
            ),
            accordion(sections, always_open=True),
        ]
    )


def auth_panel(shot: int, run_dir: Path) -> Any:
    html, _, dbc = _require()
    snap = art.authority_snapshot(run_dir)
    children: List[Any] = [
        tab_banner(
            "Authority snapshots",
            "Machine, coil map, contracts, and provenance hashes cited by this run. Missing authority is blocking.",
        )
    ]
    if snap.get("blocking_hint"):
        children.append(dbc.Alert(snap["blocking_hint"], color="danger"))
    items = snap.get("items") or []
    if not items:
        children.append(
            empty_state(
                "No authority snapshots",
                "Missing authority is a blocking error. Populate machine_authority/ and contracts — do not invent metrology.",
            )
        )
    else:
        rows = []
        for it in items:
            rel = it.get("rel") or it.get("path")
            actions = []
            if rel:
                actions = [
                    html.A("View", href=art.file_url(shot, rel), target="_blank", className="me-2"),
                    html.A("Download", href=art.file_url(shot, rel, download=True)),
                ]
            rows.append(
                html.Tr(
                    [
                        html.Td(it.get("label")),
                        html.Td(html.Code(str(rel), className="small")),
                        html.Td(it.get("detail") or "present"),
                        html.Td(actions),
                    ]
                )
            )
        children.append(
            dbc.Table(
                [
                    html.Thead(html.Tr([html.Th(h) for h in ("Authority", "Path", "Detail", "Actions")])),
                    html.Tbody(rows),
                ],
                bordered=False,
                hover=True,
                size="sm",
                responsive=True,
            )
        )
    return html.Div(children)


TAB_DEFS = (
    ("overview", "Overview"),
    ("level2", "Level-2"),
    ("residuals", "Residuals"),
    ("efit", "EFIT"),
    ("gifs", "Equilibria"),
    ("auth", "Authorities"),
    ("files", "Files"),
)

TAB_META = {
    "overview": "Run status, formed-plasma window, KPIs, and SUMMARY.",
    "level2": "FAIR-MAST measured pack — plasma, PF, magnetics, SXR, Thomson, CXRS, … (plots + CSV).",
    "measured": "FAIR-MAST measured pack — plasma, PF, magnetics, SXR, Thomson, CXRS, … (plots + CSV).",
    "residuals": "Contract residuals: synthetic vs experimental traces.",
    "efit": "FreeGSNKE vs FAIR-MAST EFIT++ archive (ADR-002) — not a live EFIT solve.",
    "gifs": "Inverse / forward / evolutive equilibrium GIFs.",
    "auth": "Snapshotted authorities and provenance hashes (fail-fast if missing).",
    "files": "Browse and download plots, CSV, JSON, and markdown.",
}

_TAB_LABELS = {k: v for k, v in TAB_DEFS}
_TAB_DEFS = TAB_DEFS


def fill_one_tab(tab_id: Optional[str], shot: Optional[int], run_dir: Optional[Path]) -> Any:
    """Build only the active results tab (lazy) for smoother UI."""
    html, _, _ = _require()
    tid = (tab_id or "overview").lower()
    if tid == "measured":
        tid = "level2"
    if shot is None or run_dir is None or not run_dir.is_dir():
        label = _TAB_LABELS.get(tid, "Overview")
        return empty_state(
            f"{label} — no shot loaded",
            "Open an existing SHOT folder to inspect products, or Reconstruct to run the full Fair-MAST → FreeGSNKE pipeline.",
            steps=[
                "Enter a MAST shot number and press Enter / Open (browse only)",
                "Or Reconstruct — prior SHOT output is archived; cached Level-2 Zarrs are reused",
                f"Use {label} once artifacts exist under SHOT/<N>/",
            ],
        )
    shot_i = int(shot)
    if tid == "level2":
        return level2_panel(shot_i, run_dir)
    if tid == "residuals":
        return residuals_panel(shot_i, run_dir)
    if tid == "efit":
        return efit_panel(shot_i, run_dir)
    if tid == "gifs":
        gifs = art.gif_paths(run_dir)[:_MAX_GIFS]
        return html.Div(
            [
                tab_banner(
                    "Equilibrium GIFs",
                    "Presentation annexes — not a substitute for residual metrics or Ip match. "
                    f"Showing up to {_MAX_GIFS} GIFs for UI speed.",
                ),
                media_gallery(
                    shot_i, gifs, run_dir, "No presentation/evolutive GIFs yet."
                ),
            ]
        )
    if tid == "auth":
        return auth_panel(shot_i, run_dir)
    if tid == "files":
        return html.Div(
            [
                tab_banner("Artifact files", "Direct download links for reviewer-facing products."),
                downloads_table(shot_i, run_dir),
            ]
        )
    return overview_panel(shot_i, run_dir)


def results_heading(shot: Optional[int], tab_id: Optional[str] = None, *, cache_ready: Optional[bool] = None, cache_note: str = "") -> Any:
    html, _, _ = _require()
    tid = (tab_id or "overview").lower()
    if tid == "measured":
        tid = "level2"
    label = _TAB_LABELS.get(tid, "Overview")
    meta = TAB_META.get(tid, "")
    run_dir = None
    # Caller may pass shot only; dossier needs run_dir from app — optional strip without path
    kids: List[Any] = []
    if shot is None:
        kids = [
            html.Div("Results browser", className="results-title"),
            html.Div(meta or "Open a shot to inspect reconstruction products.", className="results-meta"),
        ]
    else:
        kids = [
            html.Div(
                [
                    html.Span(label, className="results-title"),
                    html.Span(f"SHOT/{int(shot)}", className="results-shot-pill"),
                ],
                className="results-title-row",
            ),
            html.Div(meta, className="results-meta") if meta else None,
        ]
    return html.Div(kids, className="results-heading-wrap")


def fill_all_tabs(shot: Optional[int], run_dir: Optional[Path]) -> Dict[str, Any]:
    """Compatibility helper used by tests / tooling — prefer fill_one_tab in the app."""
    return {
        "tab-body": fill_one_tab("overview", shot, run_dir),
        "results-heading": results_heading(shot, "overview"),
    }
