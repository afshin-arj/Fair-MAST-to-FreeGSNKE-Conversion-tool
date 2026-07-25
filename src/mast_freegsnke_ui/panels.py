"""Dash panel builders for the shot results browser."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from mast_freegsnke_ui import artifacts as art
from mast_freegsnke_ui import ui_kit

_MAX_GALLERY = 4
_MAX_CSV_PREVIEW = 1
_MAX_GIFS = 3
_MAX_FILE_LINKS = 20


def _require() -> tuple[Any, Any, Any]:
    return ui_kit.require()


def _fmt_kpi(value: Any) -> str:
    return ui_kit.fmt_kpi(value)


def empty_state(title: str, body: str, *, steps: Optional[List[str]] = None, kind: str = "empty") -> Any:
    return ui_kit.empty_state(title, body, steps=steps, kind=kind)


def tab_banner(title: str, note: str) -> Any:
    return ui_kit.tab_banner(title, note)


def chip(label: str, value: Any, *, tone: str = "") -> Any:
    return ui_kit.chip(label, value, tone=tone)


def shot_dossier(
    shot: Optional[int],
    run_dir: Optional[Path],
    *,
    cache_ready: Optional[bool] = None,
    cache_note: str = "",
) -> Any:
    """Compact science context strip for fusion experts (sticky in layout)."""
    html, _, _ = _require()
    if shot is None or run_dir is None or not Path(run_dir).is_dir():
        return html.Div(
            [
                html.Span("No active shot", className="dossier-empty"),
                html.Span("Open a library entry or Start a reconstruction", className="dossier-hint"),
                html.Span(
                    ["Keys: ", html.Kbd("/"), " shot · ", html.Kbd("1–8"), " tabs · ", html.Kbd("r"), " refresh"],
                    className="dossier-keys",
                ),
            ],
            className="shot-dossier shot-dossier-empty",
        )
    k = art.overview_kpis(run_dir)
    tone = ui_kit.status_tone(k.get("status"))
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
        chip("EFIT", k.get("efit_ok"), tone=ui_kit.status_tone(k.get("efit_ok"))),
        chip("Evol. Ip", k.get("evolutive_ok"), tone=ui_kit.status_tone(k.get("evolutive_ok"))),
        chip("RMS [A]", k.get("evolutive_rms_A")),
        chip("L2 cache", cache_val, tone=cache_tone),
    ]
    if k.get("blocking_n"):
        chips.append(chip("Blocking", k.get("blocking_n"), tone="fail"))
    block_banner = ui_kit.blocking_banner(k.get("blocking") or [], title="Shot blocking errors")
    path_txt = str(Path(run_dir).as_posix())
    return html.Div(
        [
            html.Div(
                [
                    html.Div(chips, className="dossier-chips"),
                    html.Div(
                        [
                            ui_kit.copy_btn(str(int(shot)), label="Copy shot"),
                            ui_kit.copy_btn(window if window != "—" else "", label="Copy window"),
                            ui_kit.copy_btn(path_txt, label="Copy path"),
                        ],
                        className="dossier-actions",
                    ),
                ],
                className="dossier-top",
            ),
            block_banner,
            html.Div(cache_note, className="dossier-note") if cache_note else None,
            html.Span(
                ["Keys: ", html.Kbd("/"), " shot · ", html.Kbd("1–8"), " tabs · ", html.Kbd("r"), " refresh"],
                className="dossier-keys",
            ),
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
        err = st.get("error") or st.get("error_hint")
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
        dur = st.get("duration_s")
        detail_bits: List[str] = []
        if note:
            detail_bits.append(str(note))
        if dur is not None:
            try:
                detail_bits.append(f"{float(dur):.1f}s")
            except (TypeError, ValueError):
                pass
        if isinstance(hits, list) and hits:
            detail_bits.append(f"cache {len(hits)}")
        if isinstance(synced, list) and synced:
            detail_bits.append(f"sync {len(synced)}")
        elif isinstance(synced, list) and note and "local_cache" in str(note):
            detail_bits.append("no S3 sync")
        detail = " · ".join(detail_bits)[:160] if detail_bits else None
        body: List[Any] = [
            html.Span(badge, className="stage-badge"),
            html.Span(
                [
                    html.Span(str(name), className="stage-name"),
                    html.Span(detail, className="stage-note") if detail else None,
                    html.Span(str(err)[:120], className="stage-err") if err and not ok else None,
                ]
            ),
        ]
        items.append(html.Li(body, className=cls))
    if not items:
        return html.P("Waiting for first stage…", className="text-muted small mb-0")
    return html.Ul(items, className="stage-list mb-0")


def _media_mode_label(path: Path) -> Optional[str]:
    name = path.name.lower()
    rel = str(path).replace("\\", "/").lower()
    if "evolutive" in name or "/evolutive/" in rel:
        return "evolutive"
    if "inverse" in name or "inverse" in rel:
        return "inverse"
    if "forward" in name or "forward" in rel:
        return "forward"
    if name.endswith(".gif"):
        return "equilibrium"
    return None


def media_card(shot: int, path: Path, run_dir: Path) -> Any:
    html, _, dbc = _require()
    rel = art.rel_posix(path, run_dir)
    view = art.file_url_for_path(shot, path, run_dir, download=False)
    dl = art.file_url_for_path(shot, path, run_dir, download=True)
    is_gif = path.suffix.lower() == ".gif"
    mode = _media_mode_label(path)
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
                    html.Div(
                        [
                            html.Span(Path(rel).name, className="media-basename", title=rel),
                            html.Span(mode, className="media-mode-badge") if mode else None,
                        ],
                        className="media-title-row",
                    ),
                    html.Div(rel, className="media-caption text-truncate", title=rel),
                    html.Div(
                        [
                            html.A("Open", href=view, target="_blank", className="btn btn-sm btn-outline-secondary me-1"),
                            html.A("Download", href=dl, className="btn btn-sm btn-primary me-1"),
                            ui_kit.copy_btn(rel, label="Path"),
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


def downloads_table(shot: int, run_dir: Path, *, query: str = "") -> Any:
    html, dcc, dbc = _require()
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
    q = (query or "").strip().lower()
    if q:
        items = [
            it
            for it in items
            if q in str(it.get("rel") or "").lower()
            or q in str(it.get("group") or "").lower()
            or q in str(it.get("kind") or "").lower()
        ]
    # Stable group order for expert scanning
    group_order = {"summary": 0, "plots": 1, "csv": 2, "residuals": 3, "efit": 4, "gifs": 5}
    items.sort(key=lambda it: (group_order.get(str(it.get("group")), 9), str(it.get("rel") or "")))
    rows = []
    for item in items[:120]:
        rel = item["rel"]
        rows.append(
            html.Tr(
                [
                    html.Td(item["group"], className="files-group"),
                    html.Td(item["kind"]),
                    html.Td(
                        [
                            html.Code(rel, className="small me-1"),
                            ui_kit.copy_btn(rel, label="⎘"),
                        ]
                    ),
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
        return html.Div(
            [
                dcc.Input(
                    id="files-filter",
                    type="search",
                    placeholder="Filter by path / group / type…",
                    value=query or "",
                    debounce=True,
                    className="form-control form-control-sm files-filter mb-2",
                ),
                html.P(
                    "No matching artifacts." if q else "No downloadable artifacts yet.",
                    className="text-muted",
                ),
            ]
        )
    return html.Div(
        [
            dcc.Input(
                id="files-filter",
                type="search",
                placeholder="Filter by path / group / type…",
                value=query or "",
                debounce=True,
                className="form-control form-control-sm files-filter mb-2",
            ),
            html.P(
                f"Showing {len(rows)} capped rows"
                + (f" matching “{query}”" if q else "")
                + " — Download ZIP for the full pack.",
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
    snap = art.authority_snapshot(run_dir)
    summary_body = html.Div(
        [
            html.P(
                "SUMMARY opens as a file for speed — use the scorecard above for the flight-deck view.",
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
    return html.Div(
        [
            tab_banner(
                "Science overview",
                "Scorecard first. Blocking errors and authority provenance are fail-fast — never invent metrology.",
            ),
            ui_kit.blocking_banner(blocking),
            quick_links(shot, run_dir),
            ui_kit.section(
                "Scorecard",
                "Declared KPIs from SUMMARY / metrics / science_audit / EFIT archive compare.",
                ui_kit.kpi_scorecard_table(kpis),
            ),
            ui_kit.section(
                "Provenance",
                "Snapshotted authorities cited by this run (short hashes only).",
                ui_kit.provenance_strip(snap.get("items") or [])
                or html.P("No authority snapshots on disk.", className="small text-muted mb-0"),
            ),
            accordion(
                [
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
    # Sort worst-first by rms for expert triage
    def _rms_key(r: Dict[str, Any]) -> float:
        try:
            v = r.get("rms")
            return float(v) if v is not None else -1.0
        except (TypeError, ValueError):
            return -1.0

    rows_sorted = sorted(rows, key=_rms_key, reverse=True)
    table_body: List[Any] = []
    ok = metrics.get("ok") if metrics else None
    tone = ui_kit.status_tone(ok)
    if metrics:
        table_body.append(
            html.Div(
                [
                    chip("ok", ok, tone=tone),
                    chip("n_scored", metrics.get("n_scored")),
                    chip("skipped_nan", metrics.get("n_skipped_all_nan")),
                ],
                className="compare-chip-row mb-2",
            )
        )
    if rows_sorted:
        header = html.Tr(
            [
                html.Th("#"),
                html.Th("contract"),
                html.Th("rms"),
                html.Th("mae"),
                html.Th("max_abs"),
                html.Th("n"),
            ]
        )
        body = []
        for i, r in enumerate(rows_sorted, start=1):
            body.append(
                html.Tr(
                    [
                        html.Td(i, className="text-muted"),
                        html.Td(html.Code(str(r["contract"]), className="small")),
                        html.Td(_fmt(r["rms"]), className="fg-kpi-val"),
                        html.Td(_fmt(r["mae"])),
                        html.Td(_fmt(r["max_abs"])),
                        html.Td(r["n"]),
                    ],
                    className="resid-top" if i <= 3 else "",
                )
            )
        table_body.append(
            dbc.Table(
                [html.Thead(header), html.Tbody(body)],
                bordered=False,
                hover=True,
                size="sm",
                responsive=True,
                className="fg-scorecard residuals-table",
            )
        )
        if rows_sorted:
            top = rows_sorted[0]
            table_body.insert(
                1,
                html.P(
                    f"Worst RMS: {top.get('contract')} = {_fmt(top.get('rms'))} "
                    f"(sorted descending — triage top offenders first).",
                    className="small text-muted",
                ),
            )
        csv_links = []
        for csv_path in art.residual_csv_paths(run_dir)[:24]:
            rel = art.rel_posix(csv_path, run_dir)
            csv_links.append(
                html.A(
                    csv_path.name,
                    href=art.file_url(shot, rel, download=True),
                    className="compare-file-chip",
                )
            )
        if csv_links:
            table_body.append(html.Div(csv_links, className="compare-file-chip-row mt-2"))

    pngs = file_link_list(
        shot,
        art.residual_plot_paths(run_dir),
        run_dir,
        empty="No residual PNGs under report/key_plots/.",
        limit=_MAX_FILE_LINKS,
    )
    preview_paths = art.residual_plot_paths(run_dir)[:_MAX_GALLERY]
    charts_body = media_gallery(shot, preview_paths, run_dir, "No residual preview plots.") if preview_paths else None

    if not table_body and not charts_body:
        return empty_state(
            "No residuals yet",
            "Run the pipeline with contract metrics enabled.",
            kind="empty",
        )
    return html.Div(
        [
            tab_banner(
                "Contract residuals",
                "Metrics sorted by RMS (worst first). Plots are secondary — open PNGs/CSVs for deep dive.",
            ),
            ui_kit.section(
                "Metrics",
                "Per-contract residuals from reconstruction_metrics.json (declared contracts only).",
                html.Div(table_body) if table_body else html.P("No per-contract rows.", className="text-muted"),
                meta=f"{len(rows_sorted)} contract(s)",
            ),
            accordion(
                [
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
    efit_ok = efit.get("ok") if isinstance(efit, dict) else None
    lead = html.Div(
        [
            chip("archive compare", "ADR-002"),
            chip("live EFIT++", "no", tone="warn"),
            chip("ok", efit_ok, tone=ui_kit.status_tone(efit_ok)),
            chip("n_times", efit.get("n_times") if isinstance(efit, dict) else None),
        ],
        className="compare-chip-row mb-2",
    )
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
                        className="compare-file-chip",
                    )
                )
        compare_body = html.Div(
            [
                dbc.Table(
                    [html.Thead(html.Tr([html.Th("Field"), html.Th("Value")])), html.Tbody(rows)],
                    bordered=False,
                    size="sm",
                    responsive=True,
                    className="fg-scorecard",
                ),
                html.Div(links, className="compare-file-chip-row mt-2"),
            ]
        )
    if score and isinstance(score, dict):
        srows = [html.Tr([html.Td(str(k)), html.Td(str(v)[:200])]) for k, v in list(score.items())[:40]]
        score_body = dbc.Table(
            [html.Thead(html.Tr([html.Th("Metric"), html.Th("Value")])), html.Tbody(srows)],
            bordered=False,
            size="sm",
            responsive=True,
            className="fg-scorecard",
        )
    return html.Div(
        [
            tab_banner(
                "EFIT archive compare",
                "FreeGSNKE vs FAIR-MAST Level-2 EFIT++ archive (ADR-002) — not a live EFIT++ / efit-ai / Py-EFIT solve.",
            ),
            lead,
            ui_kit.section(
                "Shape scorecard",
                "Primary expert view — archive shape metrics when present.",
                score_body or html.P("No shape_scorecard.json yet.", className="small text-muted mb-0"),
            ),
            accordion(
                [
                    ("COMPARE.json fields", compare_body, False),
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

    toc_chips: List[Any] = []
    for key, lab in _L2_FAMILY_DEFS:
        n_plots = len(grouped.get(key) or [])
        n_csv = sum(1 for i in csv_light if i.get("section") == key)
        if n_plots or n_csv or key in present_keys:
            toc_chips.append(
                html.Span(
                    f"{lab} · {n_plots}p/{n_csv}c",
                    className="l2-toc-chip" + ("" if (n_plots or n_csv) else " l2-toc-chip-empty"),
                )
            )

    cal_rows = art.calibration_await_rows(run_dir)
    cal_section: Any = None
    if cal_rows:
        cal_body = dbc.Table(
            [
                html.Thead(html.Tr([html.Th(h) for h in ("Family", "Status", "Source", "Fix hint")])),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(r.get("family")),
                                html.Td(
                                    html.Span(
                                        str(r.get("status")),
                                        className="auth-status auth-status-warn",
                                    )
                                ),
                                html.Td(html.Code(str(r.get("source")), className="small")),
                                html.Td(str(r.get("hint") or ""), className="small"),
                            ]
                        )
                        for r in cal_rows
                    ]
                ),
            ],
            bordered=False,
            size="sm",
            responsive=True,
            className="fg-scorecard mb-0",
        )
        cal_section = ui_kit.section(
            "Awaiting diagnostic_calibration",
            "Channels/families without cited V→T (or equivalent) — populate configs/diagnostic_calibration.json; never invent factors.",
            cal_body,
            meta=f"{len(cal_rows)} row(s)",
        )

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
                "Family TOC + on-demand detail. Calibration-awaiting channels are listed explicitly — never invent V→T.",
            ),
            html.Div(index_bits, className="mb-2"),
            meta_links,
            cal_section,
            html.Div(
                [
                    html.Div("Family TOC", className="fg-quick-label mb-1"),
                    html.Div(toc_chips, className="l2-toc"),
                ],
                className="mb-2",
            ),
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
            "Traffic-light matrix of declared authorities. Missing / awaiting is fail-fast — do not invent metrology.",
        )
    ]
    if snap.get("blocking_hint"):
        children.append(dbc.Alert(snap["blocking_hint"], color="danger", className="py-2 small"))
    matrix = snap.get("matrix") or []
    if matrix:
        mrows = []
        for it in matrix:
            st = str(it.get("status") or ("present" if it.get("present") else "missing"))
            tone = ui_kit.status_tone(st if st != "awaiting" else "awaiting_authority")
            rel = it.get("rel")
            actions = []
            if rel:
                actions = [
                    html.A("View", href=art.file_url(shot, rel), target="_blank", className="me-2"),
                    html.A("Download", href=art.file_url(shot, rel, download=True)),
                    ui_kit.copy_btn(str(rel), label="⎘"),
                ]
            mrows.append(
                html.Tr(
                    [
                        html.Td(it.get("label")),
                        html.Td(
                            html.Span(st, className=f"auth-status auth-status-{tone or 'na'}"),
                        ),
                        html.Td(html.Code(str(rel), className="small") if rel else "—"),
                        html.Td(it.get("detail") or "—", className="small text-muted"),
                        html.Td(actions),
                    ]
                )
            )
        children.append(
            ui_kit.section(
                "Authority matrix",
                "Present vs missing vs awaiting (calibration may be awaiting until cited factors exist).",
                dbc.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [html.Th(h) for h in ("Authority", "Status", "Path", "Detail", "Actions")]
                            )
                        ),
                        html.Tbody(mrows),
                    ],
                    bordered=False,
                    hover=True,
                    size="sm",
                    responsive=True,
                    className="fg-scorecard auth-matrix",
                ),
            )
        )
    items = snap.get("items") or []
    if not items and not matrix:
        children.append(
            empty_state(
                "No authority snapshots",
                "Missing authority is a blocking error. Populate machine_authority/ and contracts — do not invent metrology.",
                kind="failed",
            )
        )
    return html.Div(children)


_COMPARE_FAMILY_DEFS: tuple[tuple[str, str], ...] = (
    ("plasma", "Plasma"),
    ("pf", "PF coils"),
    ("magnetics", "Magnetics"),
)

# Compare shows basename-aligned pairs; allow more than the single-shot gallery cap.
_COMPARE_PAIR_LIMIT = 12
_COMPARE_CSV_LIMIT = 24


def _fmt_delta(value: Any) -> str:
    """Signed delta text for scorecard (B−A)."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == 0.0:
        return "0"
    body = _fmt_kpi(abs(v))
    return f"+{body}" if v > 0 else f"−{body}"


def _compare_delta_class(value: Any) -> str:
    if value is None:
        return "compare-delta compare-delta-na"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "compare-delta compare-delta-na"
    if v > 0:
        return "compare-delta compare-delta-pos"
    if v < 0:
        return "compare-delta compare-delta-neg"
    return "compare-delta compare-delta-zero"


def _compare_status_tone(status: Any) -> str:
    s = str(status or "").strip().lower()
    if s in {"success", "ok", "succeeded", "complete", "completed"}:
        return "ok"
    if s in {"failed", "fail", "error", "blocked"}:
        return "fail"
    if s in {"running", "partial", "timeout", "warning"}:
        return "warn"
    return ""


def _enrich_compare_library_options(
    runs_dir: Path,
    library_options: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Add run status to dropdown labels for expert scanning."""
    return ui_kit.enrich_library_options(
        runs_dir,
        library_options,
        overview_kpis_fn=art.overview_kpis,
        run_dir_for_fn=art.run_dir_for,
    )


def _compare_side_empty(shot: Optional[int], *, label: str) -> Any:
    html, _, _ = _require()
    if shot is None:
        return html.P(
            f"{label}: select a SHOT folder from the library.",
            className="text-muted small compare-side-miss mb-0",
        )
    return html.Div(
        [
            html.P(
                f"{label} · SHOT/{int(shot)} is not on disk.",
                className="compare-side-miss-title mb-1",
            ),
            html.P(
                "Compare is browse-only — Open or Reconstruct that shot, then reselect it here.",
                className="small text-muted mb-0",
            ),
        ],
        className="compare-side-miss",
    )


def _compare_column_header(
    label: str,
    shot: Optional[int],
    present: bool,
    *,
    status: Any = None,
) -> Any:
    html, _, _ = _require()
    shot_txt = f"SHOT/{int(shot)}" if shot is not None else "—"
    tone = "present" if present else "missing"
    kids: List[Any] = [
        html.Span(label, className="compare-col-kicker"),
        html.Span(shot_txt, className=f"compare-col-shot compare-col-shot-{tone}"),
    ]
    if present and status is not None:
        st = _compare_status_tone(status)
        kids.append(
            html.Span(
                str(status),
                className="compare-col-status" + (f" compare-col-status-{st}" if st else ""),
            )
        )
    return html.Div(kids, className="compare-col-head")


def _compare_kpi_cell(value: Any, *, key: str = "") -> Any:
    html, _, _ = _require()
    text = _fmt_kpi(value)
    cls = "compare-kpi"
    if key in {"status", "metrics_ok", "evolutive_ok", "efit_ok"}:
        if isinstance(value, bool):
            cls += " compare-kpi-ok" if value else " compare-kpi-fail"
        elif key == "status":
            st = _compare_status_tone(value)
            if st:
                cls += f" compare-kpi-{st}"
    return html.Td(text, className=cls)


def _compare_scorecard_table(card: Dict[str, Any]) -> Any:
    html, _, dbc = _require()
    sa = card.get("shot_a")
    sb = card.get("shot_b")
    header = html.Tr(
        [
            html.Th("KPI"),
            html.Th(f"A · {sa}" if sa is not None else "A"),
            html.Th(f"B · {sb}" if sb is not None else "B"),
            html.Th("Δ (B−A)", className="compare-th-delta"),
        ]
    )
    body = []
    for row in card.get("rows") or []:
        key = str(row.get("key") or "")
        body.append(
            html.Tr(
                [
                    html.Td(row.get("label") or key, className="compare-kpi-label"),
                    _compare_kpi_cell(row.get("a"), key=key),
                    _compare_kpi_cell(row.get("b"), key=key),
                    html.Td(
                        _fmt_delta(row.get("delta")),
                        className=_compare_delta_class(row.get("delta")),
                    ),
                ]
            )
        )
    return dbc.Table(
        [html.Thead(header), html.Tbody(body)],
        bordered=False,
        hover=True,
        size="sm",
        responsive=True,
        className="compare-scorecard table-sm",
    )


def _compare_media_slot(
    shot: Optional[int],
    run_dir: Optional[Path],
    path: Optional[Path],
    *,
    side: str,
) -> Any:
    html, _, _ = _require()
    if shot is None or run_dir is None or path is None:
        return html.Div(
            f"{side} — no matching file",
            className="compare-pair-miss",
        )
    return media_card(int(shot), Path(path), Path(run_dir))


def _compare_paired_gallery(
    shot_a: Optional[int],
    run_a: Optional[Path],
    paths_a: List[Path],
    shot_b: Optional[int],
    run_b: Optional[Path],
    paths_b: List[Path],
    *,
    empty: str,
    limit: int = _COMPARE_PAIR_LIMIT,
) -> Any:
    """Basename-aligned A|B media rows (uses pair_paths_by_name)."""
    html, _, dbc = _require()
    if not paths_a and not paths_b:
        return html.P(empty, className="text-muted small mb-0")
    pairs = art.pair_paths_by_name(list(paths_a), list(paths_b))
    shown = pairs[:limit]
    rows = []
    for pair in shown:
        name = pair.get("name") or "?"
        pa = pair.get("a")
        pb = pair.get("b")
        if pa is None and pb is not None:
            badge = "B only"
            badge_cls = "b-only"
        elif pb is None and pa is not None:
            badge = "A only"
            badge_cls = "a-only"
        else:
            badge = "paired"
            badge_cls = "paired"
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Code(str(name), className="compare-pair-name"),
                            html.Span(
                                badge,
                                className=f"compare-pair-badge compare-pair-badge-{badge_cls}",
                            ),
                        ],
                        className="compare-pair-meta",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                _compare_media_slot(shot_a, run_a, pa, side="A"),
                                md=6,
                                className="compare-pair-slot",
                            ),
                            dbc.Col(
                                _compare_media_slot(shot_b, run_b, pb, side="B"),
                                md=6,
                                className="compare-pair-slot",
                            ),
                        ],
                        className="g-2",
                    ),
                ],
                className="compare-pair-row",
            )
        )
    kids: List[Any] = [html.Div(rows, className="compare-pair-list")]
    if len(pairs) > limit:
        kids.append(
            html.P(
                f"Showing {limit} of {len(pairs)} basename pairs — use Files / ZIP for the rest.",
                className="small text-muted mt-2 mb-0",
            )
        )
    return html.Div(kids)


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
    for it in items[:_COMPARE_CSV_LIMIT]:
        rel = it.get("rel")
        if not rel:
            continue
        if art.safe_resolve_under(Path(run_dir), str(rel)) is None:
            continue
        name = it.get("name") or Path(str(rel)).name
        links.append(
            html.A(
                str(name),
                href=art.file_url(int(shot), str(rel), download=True),
                className="compare-file-chip",
                title=str(rel),
            )
        )
    if not links:
        return html.P(empty, className="text-muted small mb-0")
    return html.Div(links, className="compare-file-chip-row")


def _compare_paired_csv_paths(
    shot_a: Optional[int],
    run_a: Optional[Path],
    paths_a: List[Path],
    shot_b: Optional[int],
    run_b: Optional[Path],
    paths_b: List[Path],
    *,
    empty: str,
) -> Any:
    """Basename-aligned residual CSV download chips."""
    html, _, _ = _require()
    if not paths_a and not paths_b:
        return html.P(empty, className="text-muted small mb-0")
    pairs = art.pair_paths_by_name(list(paths_a), list(paths_b))[:_COMPARE_CSV_LIMIT]
    rows = []
    for pair in pairs:
        name = str(pair.get("name") or "?")
        pa = pair.get("a")
        pb = pair.get("b")

        def _chip(shot: Optional[int], run: Optional[Path], path: Optional[Path], side: str) -> Any:
            if shot is None or run is None or path is None:
                return html.Span(f"{side}: —", className="compare-file-chip compare-file-chip-miss")
            rel = art.rel_posix(Path(path), Path(run))
            return html.A(
                f"{side}: {name}",
                href=art.file_url_for_path(int(shot), Path(path), Path(run), download=True),
                className="compare-file-chip",
                title=rel,
            )

        rows.append(
            html.Div(
                [
                    html.Code(name, className="compare-pair-name me-2"),
                    _chip(shot_a, run_a, pa, "A"),
                    _chip(shot_b, run_b, pb, "B"),
                ],
                className="compare-csv-pair",
            )
        )
    return html.Div(rows, className="compare-csv-pair-list")


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


def _compare_section(title: str, note: str, body: Any, *, meta: Optional[str] = None) -> Any:
    html, _, _ = _require()
    head_kids: List[Any] = [html.H3(title, className="compare-section-title")]
    if meta:
        head_kids.append(html.Span(meta, className="compare-section-meta"))
    return html.Section(
        [
            html.Div(head_kids, className="compare-section-head"),
            html.P(note, className="compare-section-note"),
            body,
        ],
        className="compare-section",
    )


def _compare_blocking_banner(card: Dict[str, Any]) -> Any:
    html, _, dbc = _require()
    blocks: List[Any] = []
    for side, key in (("A", "a"), ("B", "b")):
        k = card.get(key) or {}
        errs = k.get("blocking") or []
        if not errs:
            continue
        shot = card.get(f"shot_{key}")
        label = f"Shot {side}" + (f" · {shot}" if shot is not None else "")
        blocks.append(
            html.Div(
                [
                    html.Strong(label, className="me-2"),
                    html.Span("; ".join(str(e) for e in errs[:6]), className="compare-block-list"),
                ],
                className="mb-1",
            )
        )
    if not blocks:
        return None
    return dbc.Alert(
        [html.Div("Blocking errors on one or both sides", className="fw-semibold mb-1"), *blocks],
        color="danger",
        className="compare-block-alert py-2 small",
    )


def _compare_identity_strip(
    shot_a: Optional[int],
    shot_b: Optional[int],
    a_ok: bool,
    b_ok: bool,
    card: Dict[str, Any],
) -> Any:
    html, _, _ = _require()
    ka = card.get("a") or {}
    kb = card.get("b") or {}

    def _side(label: str, shot: Optional[int], ok: bool, kpis: Dict[str, Any]) -> Any:
        if shot is None:
            return html.Div(
                [
                    html.Span(label, className="compare-id-kicker"),
                    html.Span("unset", className="compare-id-shot muted"),
                ],
                className="compare-id-card compare-id-card-empty",
            )
        status = kpis.get("status") if ok else "missing"
        tone = _compare_status_tone(status) if ok else "fail"
        return html.Div(
            [
                html.Span(label, className="compare-id-kicker"),
                html.Span(f"SHOT/{int(shot)}", className="compare-id-shot"),
                html.Span(
                    str(status),
                    className="compare-id-status" + (f" compare-id-status-{tone}" if tone else ""),
                ),
                html.Span(
                    f"scored {_fmt_kpi(kpis.get('n_scored'))}" if ok else "not on disk",
                    className="compare-id-meta",
                ),
            ],
            className="compare-id-card" + ("" if ok else " compare-id-card-miss"),
        )

    return html.Div(
        [
            _side("A", shot_a, a_ok, ka),
            html.Div("vs", className="compare-id-vs"),
            _side("B", shot_b, b_ok, kb),
        ],
        className="compare-id-strip",
    )


def _compare_side_gallery_fallback(
    shot: Optional[int],
    run_dir: Optional[Path],
    paths: List[Path],
    fam_title: str,
    label: str,
) -> Any:
    html, _, _ = _require()
    empty = f"No {fam_title} plots for {label}."
    if shot is None or run_dir is None or not paths:
        return html.P(empty, className="text-muted small mb-0")
    return media_gallery(int(shot), paths[:_MAX_GALLERY], Path(run_dir), empty)


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
                "Use the A / B dropdowns above (local SHOT library)",
                "Reconstruct missing shots from Shot control if needed",
                "KPIs, Level-2 plots, residuals, and GIFs appear basename-aligned",
            ],
        )

    card = art.compare_scorecard(
        run_a if a_ok else None,
        run_b if b_ok else None,
        shot_a=shot_a,
        shot_b=shot_b,
    )

    # Expert export: TSV scorecard for clipboard (no invented numbers).
    tsv_lines = ["key\tlabel\ta\tb\tdelta"]
    for row in card.get("rows") or []:
        tsv_lines.append(
            "\t".join(
                [
                    str(row.get("key") or ""),
                    str(row.get("label") or ""),
                    str(row.get("a") if row.get("a") is not None else ""),
                    str(row.get("b") if row.get("b") is not None else ""),
                    str(row.get("delta") if row.get("delta") is not None else ""),
                ]
            )
        )
    scorecard_tsv = "\n".join(tsv_lines)

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

    n_plot_pairs = len(art.pair_paths_by_name(plots_a, plots_b))
    n_resid_pairs = len(art.pair_paths_by_name(resid_png_a, resid_png_b))
    n_gif_pairs = len(art.pair_paths_by_name(gifs_a, gifs_b))

    same_shot_note = None
    if shot_a is not None and shot_b is not None and int(shot_a) == int(shot_b):
        same_shot_note = dbc.Alert(
            "Shot A and Shot B are the same number — side-by-side will mirror identical folders.",
            color="warning",
            className="compare-same-alert py-2 small",
        )

    status_a = (card.get("a") or {}).get("status") if a_ok else None
    status_b = (card.get("b") or {}).get("status") if b_ok else None

    if a_ok and b_ok:
        measured_body: Any = html.Div(
            [
                _compare_paired_gallery(
                    shot_a,
                    run_a,
                    plots_a,
                    shot_b,
                    run_b,
                    plots_b,
                    empty=f"No {fam_title} plots on either side.",
                ),
                html.Div("CSV downloads", className="compare-subhead"),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                _compare_column_header("Shot A", shot_a, True, status=status_a),
                                _compare_side_csv_links(
                                    shot_a, run_a, csv_a, empty=f"No {fam_title} CSVs for A."
                                ),
                            ],
                            md=6,
                        ),
                        dbc.Col(
                            [
                                _compare_column_header("Shot B", shot_b, True, status=status_b),
                                _compare_side_csv_links(
                                    shot_b, run_b, csv_b, empty=f"No {fam_title} CSVs for B."
                                ),
                            ],
                            md=6,
                        ),
                    ],
                    className="g-3",
                ),
            ]
        )
        residuals_body: Any = html.Div(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                _compare_column_header("Shot A", shot_a, True, status=status_a),
                                _compare_residual_chips(run_a),
                            ],
                            md=6,
                        ),
                        dbc.Col(
                            [
                                _compare_column_header("Shot B", shot_b, True, status=status_b),
                                _compare_residual_chips(run_b),
                            ],
                            md=6,
                        ),
                    ],
                    className="g-3 mb-2",
                ),
                _compare_paired_gallery(
                    shot_a,
                    run_a,
                    resid_png_a,
                    shot_b,
                    run_b,
                    resid_png_b,
                    empty="No residual PNGs on either side.",
                ),
                html.Div("residual_*.csv", className="compare-subhead"),
                _compare_paired_csv_paths(
                    shot_a,
                    run_a,
                    resid_csv_a,
                    shot_b,
                    run_b,
                    resid_csv_b,
                    empty="No residual_*.csv on either side.",
                ),
            ]
        )
        gifs_body: Any = _compare_paired_gallery(
            shot_a,
            run_a,
            gifs_a,
            shot_b,
            run_b,
            gifs_b,
            empty="No equilibrium GIFs on either side.",
            limit=_MAX_GIFS,
        )
    else:
        measured_body = dbc.Row(
            [
                dbc.Col(
                    [
                        _compare_column_header("Shot A", shot_a, a_ok, status=status_a),
                        _compare_side_empty(shot_a, label="Shot A")
                        if not a_ok
                        else html.Div(
                            [
                                _compare_side_gallery_fallback(shot_a, run_a, plots_a, fam_title, "A"),
                                html.Div("CSV", className="compare-subhead"),
                                _compare_side_csv_links(
                                    shot_a, run_a, csv_a, empty=f"No {fam_title} CSVs for A."
                                ),
                            ]
                        ),
                    ],
                    md=6,
                    className="compare-col",
                ),
                dbc.Col(
                    [
                        _compare_column_header("Shot B", shot_b, b_ok, status=status_b),
                        _compare_side_empty(shot_b, label="Shot B")
                        if not b_ok
                        else html.Div(
                            [
                                _compare_side_gallery_fallback(shot_b, run_b, plots_b, fam_title, "B"),
                                html.Div("CSV", className="compare-subhead"),
                                _compare_side_csv_links(
                                    shot_b, run_b, csv_b, empty=f"No {fam_title} CSVs for B."
                                ),
                            ]
                        ),
                    ],
                    md=6,
                    className="compare-col",
                ),
            ],
            className="g-3 compare-row",
        )
        residuals_body = dbc.Row(
            [
                dbc.Col(
                    [
                        _compare_column_header("Shot A", shot_a, a_ok, status=status_a),
                        _compare_side_empty(shot_a, label="Shot A")
                        if not a_ok
                        else html.Div(
                            [
                                _compare_residual_chips(run_a),
                                media_gallery(
                                    int(shot_a),
                                    resid_png_a[:_MAX_GALLERY],
                                    Path(run_a),
                                    "No residual PNGs for A.",
                                ),
                            ]
                        ),
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        _compare_column_header("Shot B", shot_b, b_ok, status=status_b),
                        _compare_side_empty(shot_b, label="Shot B")
                        if not b_ok
                        else html.Div(
                            [
                                _compare_residual_chips(run_b),
                                media_gallery(
                                    int(shot_b),
                                    resid_png_b[:_MAX_GALLERY],
                                    Path(run_b),
                                    "No residual PNGs for B.",
                                ),
                            ]
                        ),
                    ],
                    md=6,
                ),
            ],
            className="g-3",
        )
        gifs_body = dbc.Row(
            [
                dbc.Col(
                    _compare_side_empty(shot_a, label="Shot A")
                    if not a_ok
                    else media_gallery(int(shot_a), gifs_a, Path(run_a), "No GIFs for A."),
                    md=6,
                ),
                dbc.Col(
                    _compare_side_empty(shot_b, label="Shot B")
                    if not b_ok
                    else media_gallery(int(shot_b), gifs_b, Path(run_b), "No GIFs for B."),
                    md=6,
                ),
            ],
            className="g-3",
        )

    return html.Div(
        [
            _compare_identity_strip(shot_a, shot_b, a_ok, b_ok, card),
            same_shot_note,
            _compare_blocking_banner(card),
            _compare_section(
                "Scorecard",
                "Declared KPIs only — Δ is B−A when both sides are numeric. No invented metrology.",
                html.Div(
                    [
                        html.Div(
                            ui_kit.copy_btn(scorecard_tsv, label="Copy scorecard TSV"),
                            className="mb-2",
                        ),
                        _compare_scorecard_table(card),
                    ]
                ),
            ),
            _compare_section(
                f"Measured · {fam_title}",
                "Existing Level-2 plots/CSVs — basename-aligned when both sides exist; no cross-shot timebase.",
                measured_body,
                meta=f"{n_plot_pairs} plot pair(s)" if (a_ok and b_ok) else None,
            ),
            _compare_section(
                "Residuals",
                "Per-shot contract metrics and residual assets (not recomputed across shots).",
                residuals_body,
                meta=f"{n_resid_pairs} plot pair(s)" if (a_ok and b_ok) else None,
            ),
            _compare_section(
                "Equilibria",
                "Inverse / forward / evolutive GIFs aligned by filename.",
                gifs_body,
                meta=f"{n_gif_pairs} GIF pair(s)" if (a_ok and b_ok) else None,
            ),
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
    lib_opts = _enrich_compare_library_options(Path(runs_dir), library_options)
    return html.Div(
        [
            tab_banner(
                "Compare two shots",
                "Browse-only. Basename-aligned KPIs, Level-2 plots, residuals, and GIFs from existing "
                "SHOT/<N>/ folders. Does not download, reconstruct, or invent a common timebase.",
            ),
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Shot A", html_for="compare-dd-a", className="fg-label"),
                                    dcc.Dropdown(
                                        id="compare-dd-a",
                                        options=lib_opts,
                                        value=int(shot_a) if shot_a is not None else None,
                                        placeholder="Select shot A…",
                                        clearable=True,
                                        className="compare-dd",
                                    ),
                                ],
                                md=4,
                                lg=4,
                            ),
                            dbc.Col(
                                html.Div(
                                    dbc.Button(
                                        "A ↔ B",
                                        id="compare-btn-swap",
                                        color="secondary",
                                        outline=True,
                                        size="sm",
                                        className="compare-swap-btn",
                                        title="Swap Shot A and Shot B",
                                    ),
                                    className="compare-swap-wrap",
                                ),
                                md=1,
                                lg=1,
                                className="d-flex align-items-end justify-content-center",
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Shot B", html_for="compare-dd-b", className="fg-label"),
                                    dcc.Dropdown(
                                        id="compare-dd-b",
                                        options=lib_opts,
                                        value=int(shot_b) if shot_b is not None else None,
                                        placeholder="Select shot B…",
                                        clearable=True,
                                        className="compare-dd",
                                    ),
                                ],
                                md=4,
                                lg=4,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Measured family", html_for="compare-family", className="fg-label"),
                                    dcc.Dropdown(
                                        id="compare-family",
                                        options=fam_opts,
                                        value=fam,
                                        clearable=False,
                                        className="compare-dd",
                                    ),
                                ],
                                md=3,
                                lg=3,
                            ),
                        ],
                        className="g-2 align-items-end",
                    ),
                ],
                className="compare-controls compare-controls-sticky",
            ),
            html.Div(
                id="compare-detail",
                children=compare_detail(runs_dir, shot_a, shot_b, fam),
                className="compare-detail",
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
    "overview": "Scorecard, blocking errors, provenance — SUMMARY on demand.",
    "level2": "Family TOC, calibration-await table, on-demand plots/CSV.",
    "measured": "Family TOC, calibration-await table, on-demand plots/CSV.",
    "residuals": "Contract residuals sorted by RMS (worst first).",
    "compare": "Browse-only A|B console — basename-aligned KPIs, Level-2, residuals, and GIFs.",
    "efit": "Archive shape scorecard first (ADR-002) — not a live EFIT solve.",
    "gifs": "Inverse / forward / evolutive equilibrium GIFs with mode badges.",
    "auth": "Authority traffic-light matrix — fail-fast if missing.",
    "files": "Grouped, filterable artifact downloads + copy path.",
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
                    "Presentation annexes labeled by mode (inverse / forward / evolutive) — not a substitute for residual metrics.",
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
                tab_banner(
                    "Artifact files",
                    "Grouped, filterable download links. Use ZIP for the full reviewer pack.",
                ),
                html.Div(id="files-table", children=downloads_table(shot_i, run_dir)),
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
