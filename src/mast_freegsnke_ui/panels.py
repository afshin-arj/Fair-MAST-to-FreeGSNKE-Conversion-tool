"""Dash panel builders for the shot results browser."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from mast_freegsnke_ui import artifacts as art

_MAX_GALLERY = 4
_MAX_CSV_PREVIEW = 1
_MAX_GIFS = 3
_MAX_FILE_LINKS = 20


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
    overall = str((progress or {}).get("status") or "")
    blocking = list((progress or {}).get("blocking_errors") or [])
    hard_fail = overall == "failed" or bool(blocking)
    pct = int(round(100 * done / n)) if stages else (8 if running else 0)
    if running and stages:
        pct = min(95, max(pct, int(round(100 * (done + 0.35) / max(n + 1, 1)))))
    if running:
        color = "info"
    elif hard_fail:
        color = "danger"
    elif overall == "success" or (done == n and n):
        color = "success"
    else:
        color = "secondary"
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
    # Always use the file server URL — never inline data-URIs (slow + huge payloads).
    return html.Div(
        [
            html.Div(
                html.Img(
                    src=view,
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
    extra = None
    if len(paths) > _MAX_GALLERY:
        extra = html.P(
            f"Showing {_MAX_GALLERY} of {len(paths)} — download the ZIP for the full set.",
            className="small text-muted mt-2 mb-0",
        )
    return html.Div([dbc.Row(cols, className="g-3"), extra])


def file_link_list(shot: int, paths: List[Path], run_dir: Path, *, empty: str, limit: int = 24) -> Any:
    """Fast expert list: open/download links only (no embedded images)."""
    html, _, _ = _require()
    if not paths:
        return html.P(empty, className="text-muted small mb-0")
    items = []
    for p in paths[:limit]:
        rel = art.rel_posix(p, run_dir)
        items.append(
            html.Li(
                [
                    html.Code(Path(rel).name, className="me-2"),
                    html.A("Open", href=art.file_url_for_path(shot, p, run_dir), target="_blank", className="me-2"),
                    html.A("Download", href=art.file_url_for_path(shot, p, run_dir, download=True)),
                    html.Span(f"  {rel}", className="text-muted small ms-2 d-none d-md-inline"),
                ],
                className="file-link-item",
            )
        )
    kids: List[Any] = [html.Ul(items, className="file-link-list mb-1")]
    if len(paths) > limit:
        kids.append(
            html.P(f"Showing {limit} of {len(paths)} — use Files tab or ZIP for the rest.", className="small text-muted mb-0")
        )
    return html.Div(kids)


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
    # Prefer quick catalog + capped image/csv lists — avoid full tree walks.
    items = list(art.catalog_quick(run_dir))
    seen = {it["rel"] for it in items}
    for group, paths in (
        ("plots", art.measured_plot_paths(run_dir)[:24]),
        ("residuals", art.residual_plot_paths(run_dir)[:16]),
        ("efit", art.efit_plot_paths(run_dir)[:16]),
        ("gifs", art.gif_paths(run_dir)[:8]),
        ("csv", art.residual_csv_paths(run_dir)[:24]),
    ):
        for p in paths:
            rel = art.rel_posix(p, run_dir)
            if rel in seen or rel.startswith("..") or art.safe_resolve_under(run_dir, rel) is None:
                continue
            seen.add(rel)
            try:
                nbytes = p.stat().st_size
            except OSError:
                nbytes = 0
            items.append(
                {
                    "rel": rel,
                    "kind": p.suffix.lstrip(".").lower() or "file",
                    "bytes": nbytes,
                    "group": group,
                }
            )
    rows = []
    for item in items[:120]:
        rel = item["rel"]
        rows.append(
            html.Tr(
                [
                    html.Td(item["group"]),
                    html.Td(item["kind"]),
                    html.Td(html.Code(rel, className="small")),
                    html.Td(f"{int(item['bytes']):,}"),
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
    return html.Div(
        [
            html.P(
                "Capped listing for speed — Download ZIP for the full pack.",
                className="small text-muted mb-2",
            ),
            dbc.Table(
                [
                    html.Thead(html.Tr([html.Th(h) for h in ("Group", "Type", "Path", "Bytes", "Actions")])),
                    html.Tbody(rows),
                ],
                bordered=False,
                hover=True,
                size="sm",
                responsive=True,
                className="downloads-table",
            ),
        ]
    )


def overview_panel(shot: int, run_dir: Path) -> Any:
    html, dcc, dbc = _require()
    kpis = art.overview_kpis(run_dir)
    blocking = kpis.get("blocking") or []
    # Keep Overview instant: no Markdown parse/render — link out to SUMMARY.md.
    summary_body = html.Div(
        [
            html.P(
                "SUMMARY is opened as a file for speed. Use the links below (or KPIs above) instead of in-page Markdown.",
                className="small text-muted mb-2",
            ),
            html.Div(
                [
                    html.A(
                        "Open SUMMARY.md",
                        href=art.file_url(shot, "01_summary/SUMMARY.md"),
                        target="_blank",
                        className="btn btn-sm btn-outline-secondary me-1",
                    )
                    if art.safe_resolve_under(run_dir, "01_summary/SUMMARY.md")
                    else None,
                    html.A(
                        "SUMMARY.json",
                        href=art.file_url(shot, "01_summary/SUMMARY.json"),
                        target="_blank",
                        className="btn btn-sm btn-outline-secondary me-1",
                    )
                    if art.safe_resolve_under(run_dir, "01_summary/SUMMARY.json")
                    else None,
                    html.A(
                        "Download SUMMARY.md",
                        href=art.file_url(shot, "01_summary/SUMMARY.md", download=True),
                        className="btn btn-sm btn-outline-secondary",
                    )
                    if art.safe_resolve_under(run_dir, "01_summary/SUMMARY.md")
                    else None,
                ]
            ),
            html.Pre(art.overview_text(run_dir), className="overview-pre mt-3"),
        ],
        className="summary-wrap",
    )
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
                "Status, formed-plasma window, and KPIs. Expand only what you need — SUMMARY opens as a file for speed.",
            ),
            quick_links(shot, run_dir),
            accordion(
                [
                    ("Key performance indicators", kpi_strip(kpis), False),
                    ("Blocking errors", blocking_body, False),
                    ("Downloads", export_bar(shot, run_dir), False),
                    ("SUMMARY (file links + text digest)", summary_body, False),
                ]
            ),
        ]
    )


def residuals_panel(shot: int, run_dir: Path) -> Any:
    html, dcc, dbc = _require()
    metrics = art.load_metrics(run_dir)
    rows = art.metrics_table_rows(metrics)
    table_body: Any = None
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
        for csv_path in art.residual_csv_paths(run_dir)[:24]:
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

    pngs = file_link_list(
        shot,
        art.residual_plot_paths(run_dir),
        run_dir,
        empty="No residual PNGs under report/key_plots/.",
        limit=_MAX_FILE_LINKS,
    )
    # One small gallery only (optional visual) — avoids Plotly parse cost on every tab open.
    preview_paths = art.residual_plot_paths(run_dir)[:_MAX_GALLERY]
    charts_body = media_gallery(shot, preview_paths, run_dir, "No residual preview plots.") if preview_paths else None

    if not table_body and not charts_body:
        return empty_state("No residuals yet", "Run the pipeline with contract metrics enabled.")
    return html.Div(
        [
            tab_banner(
                "Contract residuals",
                "Metrics table first. Plotly charts are skipped for speed — open PNGs/CSVs, or use the light preview below.",
            ),
            accordion(
                [
                    ("Metrics table & CSV", html.Div(table_body) if table_body else None, False),
                    ("Residual PNG links", pngs, False),
                    ("Light PNG preview", charts_body, False),
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
                    ("COMPARE.json fields", compare_body, False),
                    ("Shape scorecard", score_body, False),
                    (
                        "EFIT plots",
                        file_link_list(
                            shot,
                            art.efit_plot_paths(run_dir),
                            run_dir,
                            empty="No EFIT compare plots yet.",
                            limit=_MAX_FILE_LINKS,
                        ),
                        False,
                    ),
                    (
                        "Light PNG preview",
                        media_gallery(
                            shot,
                            art.efit_plot_paths(run_dir)[:_MAX_GALLERY],
                            run_dir,
                            "No EFIT compare plots yet.",
                        ),
                        False,
                    ),
                ]
            ),
        ]
    )


_L2_FAMILY_DEFS: tuple[tuple[str, str], ...] = (
    ("plasma", "Plasma"),
    ("pf", "PF coils"),
    ("magnetics", "Magnetics"),
    ("geometry", "Geometry"),
    ("summary", "Summary profiles"),
    ("pulse_schedule", "Pulse schedule"),
    ("spectrometer", "Spectrometer (visible)"),
    ("soft_x_rays", "Soft X-rays"),
    ("thomson", "Thomson scattering"),
    ("cxrs", "CXRS"),
    ("gas", "Gas injection"),
    ("equilibrium_l2", "Equilibrium L2 scalars"),
)


def _csv_section_block(
    shot: int,
    run_dir: Path,
    section: str,
    items: List[Dict[str, Any]],
    *,
    with_preview: bool = False,
) -> Any:
    """CSV inventory for one Level-2 family (link table; preview optional)."""
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
        if not with_preview or len(previews) >= _MAX_CSV_PREVIEW:
            continue
        path = art.safe_resolve_under(run_dir, rel)
        if path is not None and int(it.get("bytes") or 0) <= 400_000:
            preview = l2.csv_preview_rows(path, max_bytes=400_000)
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
    kids: List[Any] = [
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
            className="mb-2",
        )
    ]
    if previews:
        kids.append(html.Div(previews))
    else:
        kids.append(
            html.P(
                "Open/Download CSV above. Inline preview is skipped on tab open for speed.",
                className="small text-muted mb-0",
            )
        )
    return html.Div(kids)


def level2_family_detail(shot: int, run_dir: Path, family_key: str) -> Any:
    """Full plots + CSV for one Level-2 family (built on demand)."""
    html, _, dbc = _require()
    from mast_freegsnke_ui import level2 as l2

    key = (family_key or "plasma").strip().lower()
    title = dict(_L2_FAMILY_DEFS).get(key, key)
    grouped = l2.measured_plots_grouped(run_dir)
    # Catalog-first inventory; light optional-folder scan only.
    csvs = l2.measured_csv_inventory(run_dir, disk_walk=True)
    plots = grouped.get(key) or []
    csv_block = _csv_section_block(shot, run_dir, key, csvs, with_preview=False)
    plot_block = (
        file_link_list(shot, plots, run_dir, empty=f"No {title} plots.", limit=_MAX_FILE_LINKS)
        if plots
        else html.P(f"No {title} plots in this pack.", className="small text-muted")
    )
    kids: List[Any] = [
        html.H3(title, className="h6 text-info mb-2"),
        html.Div([html.Div("Plots", className="fg-quick-label mb-1"), plot_block], className="mb-3"),
    ]
    if key == "plasma" and plots:
        kids.append(
            html.Div(
                [
                    html.Div("Quick preview", className="fg-quick-label mb-2"),
                    media_gallery(shot, plots[:2], run_dir, ""),
                ],
                className="mb-3",
            )
        )
    kids.append(
        html.Div(
            [
                html.Div("CSV", className="fg-quick-label mb-1"),
                csv_block
                if csv_block is not None
                else html.P(f"No {title} CSV files.", className="small text-muted mb-0"),
            ]
        )
    )
    return html.Div(kids, className="l2-family-detail")


def level2_panel(shot: int, run_dir: Path) -> Any:
    """FAIR-MAST Level-2 — fast shell; one family detail at a time (all families kept)."""
    html, dcc, dbc = _require()
    from mast_freegsnke_ui import level2 as l2

    catalog = l2.load_measured_catalog(run_dir)
    grouped = l2.measured_plots_grouped(run_dir)
    # Cheap presence: plots + catalog paths only (no deep CSV walk on tab open).
    csv_light = l2.measured_csv_inventory(run_dir, disk_walk=False)
    status = l2.level2_status_files(run_dir)
    if not catalog and not grouped and not csv_light:
        return empty_state(
            "No Level-2 measured pack yet",
            "Run the pipeline with enable_experimental_data so 02_measured_data/ is built from the FAIR-MAST extract.",
        )

    present_keys = []
    for key, _lab in _L2_FAMILY_DEFS:
        if grouped.get(key) or any(i.get("section") == key for i in csv_light):
            present_keys.append(key)
    if not present_keys:
        present_keys = ["plasma"]

    index_bits: List[Any] = []
    if catalog:
        fams = catalog.get("families") or {}
        index_bits.append(
            html.P(
                f"Shot {catalog.get('shot', shot)} · families={len(fams) if isinstance(fams, dict) else 0} · "
                f"plots={len(catalog.get('plots') or [])} · window={catalog.get('window_s')}",
                className="small text-muted mb-1",
            )
        )
        if catalog.get("warnings"):
            index_bits.append(
                html.Ul([html.Li(str(w)) for w in list(catalog.get("warnings") or [])[:6]], className="small")
            )
    else:
        index_bits.append(html.P("catalog.json not found — listing files from disk.", className="small text-muted"))

    opt = status.get("optional") or {}
    opt_groups = (opt.get("groups") or {}) if isinstance(opt, dict) else {}
    avail = [k for k, v in opt_groups.items() if isinstance(v, dict) and v.get("available")]
    missing = [k for k, v in opt_groups.items() if isinstance(v, dict) and not v.get("available")]
    if avail or missing:
        index_bits.append(
            html.P(
                f"Optional L2 — available: {', '.join(avail) or 'none'} · missing (warn): {', '.join(missing) or 'none'}",
                className="small mb-0",
            )
        )

    default_key = "plasma" if "plasma" in present_keys else present_keys[0]
    options = [{"label": lab, "value": key} for key, lab in _L2_FAMILY_DEFS if key in present_keys]
    # Keep every known family selectable so optional packs appear after reconstruct.
    for key, lab in _L2_FAMILY_DEFS:
        if key not in present_keys:
            options.append({"label": f"{lab} (empty)", "value": key})

    meta_links = html.Div(
        [
            html.A(
                "L1 STATUS",
                href=art.file_url(shot, "02_measured_data/l1/STATUS.json"),
                target="_blank",
                className="btn btn-sm btn-outline-secondary me-1",
            )
            if art.safe_resolve_under(run_dir, "02_measured_data/l1/STATUS.json")
            else None,
            html.A(
                "L3 STATUS",
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
        ],
        className="mb-2",
    )

    return html.Div(
        [
            tab_banner(
                "FAIR-MAST Level-2 measured data",
                "Pick a family below — plots and CSV load on demand so tab switches stay smooth. Everything remains available.",
            ),
            html.Div(index_bits, className="mb-2"),
            meta_links,
            html.Div(
                [
                    html.Span("Family", className="fg-quick-label"),
                    dcc.RadioItems(
                        id="l2-family",
                        options=options,
                        value=default_key,
                        className="l2-family-radio",
                        inputClassName="me-1",
                        labelClassName="l2-family-option me-2",
                        inline=True,
                    ),
                ],
                className="fg-quick-bar mb-3",
            ),
            # Initial detail for default family (tests + first paint); callback refreshes on change.
            html.Div(
                level2_family_detail(shot, run_dir, default_key),
                id="l2-detail",
                className="l2-detail",
            ),
        ],
        className="l2-panel",
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


_COMPARE_FAMILY_DEFS: tuple[tuple[str, str], ...] = (
    ("plasma", "Plasma"),
    ("pf", "PF coils"),
    ("magnetics", "Magnetics"),
)


def _compare_side_empty(shot: Optional[int], *, label: str) -> Any:
    html, _, _ = _require()
    if shot is None:
        return html.P(
            f"{label}: pick a shot from the library dropdown.",
            className="text-muted small compare-side-miss mb-0",
        )
    return html.Div(
        [
            html.P(
                f"{label} · SHOT/{int(shot)} is missing on disk.",
                className="text-muted small mb-1",
            ),
            html.P(
                "Compare is browse-only — Open or Reconstruct that shot first, then reselect it here.",
                className="small text-muted mb-0",
            ),
        ],
        className="compare-side-miss",
    )


def _compare_column_header(label: str, shot: Optional[int], present: bool) -> Any:
    html, _, _ = _require()
    shot_txt = f"SHOT/{int(shot)}" if shot is not None else "—"
    tone = "present" if present else "missing"
    return html.Div(
        [
            html.Span(label, className="compare-col-kicker"),
            html.Span(shot_txt, className=f"compare-col-shot compare-col-shot-{tone}"),
        ],
        className="compare-col-head",
    )


def _compare_scorecard_table(card: Dict[str, Any]) -> Any:
    html, _, dbc = _require()
    sa = card.get("shot_a")
    sb = card.get("shot_b")
    header = html.Tr(
        [
            html.Th("KPI"),
            html.Th(f"A · {sa}" if sa is not None else "A"),
            html.Th(f"B · {sb}" if sb is not None else "B"),
            html.Th("Δ (B−A)"),
        ]
    )
    body = []
    for row in card.get("rows") or []:
        body.append(
            html.Tr(
                [
                    html.Td(row.get("label") or row.get("key")),
                    html.Td(_fmt_kpi(row.get("a"))),
                    html.Td(_fmt_kpi(row.get("b"))),
                    html.Td(_fmt_kpi(row.get("delta"))),
                ]
            )
        )
    return dbc.Table(
        [html.Thead(header), html.Tbody(body)],
        bordered=False,
        hover=True,
        size="sm",
        responsive=True,
        className="compare-scorecard",
    )


def _compare_side_gallery(
    shot: Optional[int],
    run_dir: Optional[Path],
    paths: List[Path],
    *,
    empty: str,
) -> Any:
    """Plot/GIF gallery only (no duplicate file-link dump)."""
    html, _, _ = _require()
    if shot is None or run_dir is None or not Path(run_dir).is_dir():
        return html.P(empty, className="text-muted small mb-0")
    if not paths:
        return html.P(empty, className="text-muted small mb-0")
    return media_gallery(int(shot), paths[:_MAX_GALLERY], Path(run_dir), empty)


def _compare_side_csv_links(
    shot: Optional[int],
    run_dir: Optional[Path],
    items: List[Dict[str, Any]],
    *,
    empty: str,
) -> Any:
    html, _, _ = _require()
    if shot is None or run_dir is None or not items:
        return html.P(empty, className="text-muted small mb-0")
    links = []
    for it in items[:_MAX_FILE_LINKS]:
        rel = it.get("rel")
        if not rel:
            continue
        # Reject traversal; only serve paths under the run dir.
        if art.safe_resolve_under(Path(run_dir), str(rel)) is None:
            continue
        name = it.get("name") or Path(str(rel)).name
        links.append(
            html.A(
                str(name),
                href=art.file_url(int(shot), str(rel), download=True),
                className="btn btn-sm btn-outline-secondary me-1 mb-1",
            )
        )
    if not links:
        return html.P(empty, className="text-muted small mb-0")
    return html.Div(links)


def _compare_residual_chips(run_dir: Optional[Path]) -> Any:
    html, _, _ = _require()
    if run_dir is None or not Path(run_dir).is_dir():
        return html.P("No metrics.", className="text-muted small mb-0")
    metrics = art.load_metrics(Path(run_dir))
    if not metrics:
        return html.P("No reconstruction_metrics.json.", className="text-muted small mb-0")
    ok = metrics.get("ok")
    if ok is True:
        tone = "ok"
    elif ok is False:
        tone = "fail"
    else:
        tone = ""
    return html.Div(
        [
            chip("ok", ok, tone=tone),
            chip("n_scored", metrics.get("n_scored")),
            chip("skipped_nan", metrics.get("n_skipped_all_nan")),
        ],
        className="compare-chip-row",
    )


def compare_detail(
    runs_dir: Path,
    shot_a: Optional[int],
    shot_b: Optional[int],
    family: str = "plasma",
) -> Any:
    """Browse-only side-by-side body for two finished SHOT folders."""
    html, _, dbc = _require()
    from mast_freegsnke_ui import level2 as l2

    runs_dir = Path(runs_dir)
    fam = (family or "plasma").strip().lower()
    if fam not in {k for k, _ in _COMPARE_FAMILY_DEFS}:
        fam = "plasma"
    fam_title = dict(_COMPARE_FAMILY_DEFS).get(fam, fam)

    run_a = art.run_dir_for(runs_dir, int(shot_a)) if shot_a is not None else None
    run_b = art.run_dir_for(runs_dir, int(shot_b)) if shot_b is not None else None
    a_ok = run_a is not None and run_a.is_dir()
    b_ok = run_b is not None and run_b.is_dir()

    if not a_ok and not b_ok:
        return empty_state(
            "Select two reconstructed shots",
            "Compare never downloads or solves. Pick shots that already have SHOT/<N>/ products.",
            steps=[
                "Use the A / B dropdowns above (library of local SHOT folders)",
                "Reconstruct missing shots from Shot control if needed",
                "KPIs, Level-2 plots, residuals, and GIFs appear side-by-side",
            ],
        )

    card = art.compare_scorecard(
        run_a if a_ok else None,
        run_b if b_ok else None,
        shot_a=shot_a,
        shot_b=shot_b,
    )

    # Measured family plots / CSVs
    plots_a = (l2.measured_plots_grouped(run_a).get(fam) or []) if a_ok else []
    plots_b = (l2.measured_plots_grouped(run_b).get(fam) or []) if b_ok else []
    csv_a = (
        [it for it in l2.measured_csv_inventory(run_a, disk_walk=True) if it.get("section") == fam]
        if a_ok
        else []
    )
    csv_b = (
        [it for it in l2.measured_csv_inventory(run_b, disk_walk=True) if it.get("section") == fam]
        if b_ok
        else []
    )

    resid_png_a = art.residual_plot_paths(run_a) if a_ok else []
    resid_png_b = art.residual_plot_paths(run_b) if b_ok else []
    resid_csv_a = art.residual_csv_paths(run_a) if a_ok else []
    resid_csv_b = art.residual_csv_paths(run_b) if b_ok else []
    gifs_a = art.gif_paths(run_a)[:_MAX_GIFS] if a_ok else []
    gifs_b = art.gif_paths(run_b)[:_MAX_GIFS] if b_ok else []

    same_shot_note = None
    if shot_a is not None and shot_b is not None and int(shot_a) == int(shot_b):
        same_shot_note = dbc.Alert(
            "Shot A and Shot B are the same number — side-by-side will mirror identical folders.",
            color="warning",
            className="py-2 small",
        )

    def _measured_col(label: str, shot: Optional[int], ok: bool, run: Optional[Path], plots, csvs) -> Any:
        return dbc.Col(
            [
                _compare_column_header(label, shot, ok),
                _compare_side_empty(shot, label=label)
                if not ok
                else html.Div(
                    [
                        _compare_side_gallery(
                            shot, run, plots, empty=f"No {fam_title} plots for {label}."
                        ),
                        html.Div("CSV", className="fg-quick-label mt-2 mb-1"),
                        _compare_side_csv_links(
                            shot, run, csvs, empty=f"No {fam_title} CSVs for {label}."
                        ),
                    ]
                ),
            ],
            md=6,
            className="compare-col",
        )

    measured_row = dbc.Row(
        [
            _measured_col("Shot A", shot_a, a_ok, run_a, plots_a, csv_a),
            _measured_col("Shot B", shot_b, b_ok, run_b, plots_b, csv_b),
        ],
        className="g-3 compare-row",
    )

    def _resid_col(label: str, shot: Optional[int], ok: bool, run: Optional[Path], pngs, csvs) -> Any:
        return dbc.Col(
            [
                _compare_column_header(label, shot, ok),
                _compare_side_empty(shot, label=label)
                if not ok
                else html.Div(
                    [
                        _compare_residual_chips(run),
                        _compare_side_gallery(shot, run, pngs, empty=f"No residual PNGs for {label}."),
                        html.Div("residual_*.csv", className="fg-quick-label mt-2 mb-1"),
                        file_link_list(
                            int(shot),
                            csvs,
                            Path(run),
                            empty=f"No residual_*.csv for {label}.",
                            limit=_MAX_FILE_LINKS,
                        )
                        if shot is not None and run is not None
                        else None,
                    ]
                ),
            ],
            md=6,
            className="compare-col",
        )

    residuals_row = dbc.Row(
        [
            _resid_col("Shot A", shot_a, a_ok, run_a, resid_png_a, resid_csv_a),
            _resid_col("Shot B", shot_b, b_ok, run_b, resid_png_b, resid_csv_b),
        ],
        className="g-3 compare-row",
    )

    gifs_row = dbc.Row(
        [
            dbc.Col(
                [
                    _compare_column_header("Shot A", shot_a, a_ok),
                    _compare_side_empty(shot_a, label="Shot A")
                    if not a_ok
                    else media_gallery(
                        int(shot_a), gifs_a, Path(run_a), "No equilibrium GIFs for A."
                    ),
                ],
                md=6,
                className="compare-col",
            ),
            dbc.Col(
                [
                    _compare_column_header("Shot B", shot_b, b_ok),
                    _compare_side_empty(shot_b, label="Shot B")
                    if not b_ok
                    else media_gallery(
                        int(shot_b), gifs_b, Path(run_b), "No equilibrium GIFs for B."
                    ),
                ],
                md=6,
                className="compare-col",
            ),
        ],
        className="g-3 compare-row",
    )

    return html.Div(
        [
            same_shot_note,
            html.H3("Scorecard", className="h6 text-info mb-2"),
            _compare_scorecard_table(card),
            html.Hr(className="compare-sep"),
            html.H3(f"Measured · {fam_title}", className="h6 text-info mb-2"),
            html.P(
                "Existing Level-2 plots/CSVs side-by-side — no cross-shot time alignment.",
                className="small text-muted",
            ),
            measured_row,
            html.Hr(className="compare-sep"),
            html.H3("Residuals", className="h6 text-info mb-2"),
            html.P(
                "Per-shot contract metrics and residual assets (not recomputed across shots).",
                className="small text-muted",
            ),
            residuals_row,
            html.Hr(className="compare-sep"),
            html.H3("Equilibria", className="h6 text-info mb-2"),
            gifs_row,
        ],
        className="compare-detail-inner",
    )


def compare_panel(
    runs_dir: Path,
    *,
    library_options: List[Dict[str, Any]],
    shot_a: Optional[int] = None,
    shot_b: Optional[int] = None,
    family: str = "plasma",
) -> Any:
    """Compare tab shell: A/B pickers + measured family + detail region."""
    html, dcc, dbc = _require()
    fam = (family or "plasma").strip().lower()
    if fam not in {k for k, _ in _COMPARE_FAMILY_DEFS}:
        fam = "plasma"
    fam_opts = [{"label": lab, "value": key} for key, lab in _COMPARE_FAMILY_DEFS]
    return html.Div(
        [
            tab_banner(
                "Compare two shots",
                "Browse-only. Reuses existing SHOT/<N>/ plots and CSVs side-by-side. "
                "Does not download, reconstruct, or invent a common timebase.",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Shot A", html_for="compare-dd-a", className="fg-label"),
                            dcc.Dropdown(
                                id="compare-dd-a",
                                options=library_options,
                                value=int(shot_a) if shot_a is not None else None,
                                placeholder="Select shot A…",
                                clearable=True,
                            ),
                        ],
                        md=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Shot B", html_for="compare-dd-b", className="fg-label"),
                            dcc.Dropdown(
                                id="compare-dd-b",
                                options=library_options,
                                value=int(shot_b) if shot_b is not None else None,
                                placeholder="Select shot B…",
                                clearable=True,
                            ),
                        ],
                        md=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Measured family", html_for="compare-family", className="fg-label"),
                            dcc.Dropdown(
                                id="compare-family",
                                options=fam_opts,
                                value=fam,
                                clearable=False,
                            ),
                        ],
                        md=4,
                    ),
                ],
                className="g-2 mb-3 compare-controls",
            ),
            html.Div(
                id="compare-detail",
                children=compare_detail(runs_dir, shot_a, shot_b, fam),
            ),
        ],
        className="compare-panel",
    )


def default_compare_pair(
    active_shot: Optional[int],
    library_shots: List[int],
) -> tuple[Optional[int], Optional[int]]:
    """Default A = active (or first library); B = first other library shot."""
    shots = [int(s) for s in library_shots]
    a: Optional[int] = None
    if active_shot is not None:
        try:
            a = int(active_shot)
        except (TypeError, ValueError):
            a = None
    if a is None and shots:
        a = shots[0]
    b: Optional[int] = None
    for s in shots:
        if a is None or s != a:
            b = s
            break
    return a, b


TAB_DEFS = (
    ("overview", "Overview"),
    ("level2", "Level-2"),
    ("residuals", "Residuals"),
    ("compare", "Compare"),
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
    "compare": "Browse-only side-by-side of two finished SHOT folders (KPIs, measured, residuals, GIFs).",
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
    # Compare is browse-only dual-shot; built by app.create_app via compare_panel.
    if tid == "compare":
        return empty_state(
            "Compare",
            "Select Shot A and Shot B in the Compare tab controls (local SHOT library).",
            steps=[
                "Open the Compare tab",
                "Pick two finished shots from the library",
                "Review scorecard, measured, residuals, and equilibria side-by-side",
            ],
        )
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


def results_heading(shot: Optional[int], tab_id: Optional[str] = None) -> Any:
    html, _, _ = _require()
    tid = (tab_id or "overview").lower()
    if tid == "measured":
        tid = "level2"
    label = _TAB_LABELS.get(tid, "Overview")
    meta = TAB_META.get(tid, "")
    if tid == "compare":
        kids_c: List[Any] = [
            html.Div(
                [
                    html.Span(label, className="results-title"),
                    html.Span("A vs B", className="results-shot-pill"),
                ],
                className="results-title-row",
            ),
            html.Div(meta, className="results-meta") if meta else None,
        ]
        return html.Div(kids_c, className="results-heading-wrap")
    if shot is None:
        kids: List[Any] = [
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
