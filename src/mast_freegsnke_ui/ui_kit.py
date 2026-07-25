"""Shared expert-console UI primitives (status tones, KPIs, banners, copy).

Keep panels dense and consistent — no invented metrology, no decorative chrome.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def require() -> tuple[Any, Any, Any]:
    from dash import dcc, html
    import dash_bootstrap_components as dbc

    return html, dcc, dbc


def status_tone(status: Any) -> str:
    s = str(status or "").strip().lower()
    if s in {"success", "ok", "succeeded", "complete", "completed", "present", "populated", "yes", "true"}:
        return "ok"
    if s in {"failed", "fail", "error", "blocked", "missing", "no", "false"}:
        return "fail"
    if s in {
        "running",
        "partial",
        "timeout",
        "warning",
        "warn",
        "awaiting",
        "awaiting_authority",
        "unknown",
    }:
        return "warn"
    if isinstance(status, bool):
        return "ok" if status else "fail"
    return ""


def fmt_kpi(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if abs(value) >= 1e4 or (abs(value) > 0 and abs(value) < 1e-2):
            return f"{value:.3g}"
        return f"{value:.4g}"
    return str(value)


def fmt_delta(value: Any) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == 0.0:
        return "0"
    body = fmt_kpi(abs(v))
    return f"+{body}" if v > 0 else f"−{body}"


def delta_class(value: Any) -> str:
    if value is None:
        return "fg-delta fg-delta-na"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "fg-delta fg-delta-na"
    if v > 0:
        return "fg-delta fg-delta-pos"
    if v < 0:
        return "fg-delta fg-delta-neg"
    return "fg-delta fg-delta-zero"


def chip(label: str, value: Any, *, tone: str = "") -> Any:
    html, _, _ = require()
    cls = "fg-chip" + (f" fg-chip-{tone}" if tone else "")
    return html.Span(
        [html.Span(str(label), className="fg-chip-k"), html.Span(fmt_kpi(value), className="fg-chip-v")],
        className=cls,
    )


def copy_btn(text: str, *, label: str = "Copy") -> Any:
    """Clipboard button; clientside binder listens for [data-clipboard-text]."""
    html, _, _ = require()
    if not text:
        return None
    return html.Button(
        label,
        type="button",
        className="fg-copy-btn",
        **{"data-clipboard-text": str(text)},
        title=f"Copy {text}",
    )


def copyable_code(text: str) -> Any:
    html, _, _ = require()
    return html.Span(
        [html.Code(str(text), className="fg-copy-code"), copy_btn(str(text), label="⎘")],
        className="fg-copyable",
    )


def empty_state(
    title: str,
    body: str,
    *,
    steps: Optional[List[str]] = None,
    kind: str = "empty",
) -> Any:
    """kind: empty | partial | failed | awaiting"""
    html, _, _ = require()
    kickers = {
        "empty": "No shot context",
        "partial": "Partial products",
        "failed": "Blocked / failed",
        "awaiting": "Awaiting authority",
    }
    kids: List[Any] = [
        html.Div(kickers.get(kind, "No shot context"), className=f"empty-kicker empty-kicker-{kind}"),
        html.H5(title, className="empty-title"),
        html.P(body, className="empty-body mb-0"),
    ]
    if steps:
        kids.append(html.Ol([html.Li(s) for s in steps], className="empty-steps"))
    return html.Div(kids, className=f"empty-state empty-state-{kind}")


def tab_banner(title: str, note: str) -> Any:
    html, _, _ = require()
    return html.Div(
        [
            html.H6(title, className="tab-banner-title"),
            html.P(note, className="tab-banner-note"),
        ],
        className="tab-banner",
    )


def section(title: str, note: str, body: Any, *, meta: Optional[str] = None) -> Any:
    html, _, _ = require()
    head: List[Any] = [html.H3(title, className="fg-section-title")]
    if meta:
        head.append(html.Span(meta, className="fg-section-meta"))
    return html.Section(
        [
            html.Div(head, className="fg-section-head"),
            html.P(note, className="fg-section-note") if note else None,
            body,
        ],
        className="fg-section",
    )


def blocking_banner(
    errors: Sequence[Any],
    *,
    title: str = "Blocking errors — fail-fast (do not invent metrology)",
) -> Any:
    html, _, dbc = require()
    errs = [e for e in errors if e is not None and str(e).strip()]
    if not errs:
        return None
    return dbc.Alert(
        [
            html.Div(title, className="fw-semibold mb-1"),
            html.Ul([html.Li(str(e)) for e in errs[:8]], className="mb-0 small"),
        ],
        color="danger",
        className="fg-blocking-banner py-2",
    )


def provenance_strip(items: List[Dict[str, Any]]) -> Any:
    """Compact hash / version chips for audit."""
    html, _, _ = require()
    chips = []
    for it in items:
        label = it.get("label") or "?"
        detail = it.get("detail") or ("present" if it.get("present") else "missing")
        tone = status_tone("ok" if it.get("present") else "missing")
        chips.append(chip(str(label), detail, tone=tone or ""))
    if not chips:
        return None
    return html.Div(chips, className="fg-prov-strip")


def kpi_scorecard_rows(kpis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Single-shot scorecard rows shared by Overview (and dossier logic)."""
    window = "—"
    if kpis.get("t_start") is not None or kpis.get("t_end") is not None:
        window = f"{fmt_kpi(kpis.get('t_start'))} → {fmt_kpi(kpis.get('t_end'))} s"
    dt = None
    try:
        if kpis.get("t_start") is not None and kpis.get("t_end") is not None:
            dt = float(kpis["t_end"]) - float(kpis["t_start"])
    except (TypeError, ValueError):
        dt = None
    modes = kpis.get("modes") or {}
    mode_txt = None
    if isinstance(modes, dict) and modes:
        mode_txt = ", ".join(f"{a}={b}" for a, b in modes.items())
    return [
        {"key": "status", "label": "Status", "value": kpis.get("status"), "tone": status_tone(kpis.get("status"))},
        {"key": "modes", "label": "Modes", "value": mode_txt},
        {"key": "window", "label": "Window [s]", "value": window},
        {"key": "window_dt", "label": "Window Δt [s]", "value": dt},
        {"key": "n_scored", "label": "Contracts scored", "value": kpis.get("n_scored")},
        {
            "key": "metrics_ok",
            "label": "Metrics ok",
            "value": kpis.get("metrics_ok"),
            "tone": status_tone(kpis.get("metrics_ok")),
        },
        {
            "key": "evolutive_ok",
            "label": "Evolutive Ip ok",
            "value": kpis.get("evolutive_ok"),
            "tone": status_tone(kpis.get("evolutive_ok")),
        },
        {"key": "evolutive_rms_A", "label": "Evolutive Ip RMS [A]", "value": kpis.get("evolutive_rms_A")},
        {
            "key": "profile_source",
            "label": "Profile source (ADR-004)",
            "value": kpis.get("profile_source"),
            "tone": (
                "ok"
                if kpis.get("profile_source") == "profile_trajectory_authority"
                else ("warn" if kpis.get("profile_traj_status") and str(kpis.get("profile_traj_status")).startswith("skipped") else "")
            ),
        },
        {
            "key": "profile_fit_mode",
            "label": "Profile fit mode",
            "value": kpis.get("profile_fit_mode"),
        },
        {
            "key": "profile_n_knots",
            "label": "Profile knots",
            "value": kpis.get("profile_n_knots"),
        },
        {
            "key": "planner_status",
            "label": "Planner status (ADR-004)",
            "value": kpis.get("planner_status"),
            "tone": (
                "ok"
                if kpis.get("planner_status") == "ok"
                else (
                    "warn"
                    if kpis.get("planner_status")
                    in ("voltage_exceeds_measured_peak_margin", "voltage_limit_violations")
                    or kpis.get("planner_status")
                    else ""
                )
            ),
        },
        {
            "key": "planner_rms_V",
            "label": "Planner ΔV RMS [V]",
            "value": kpis.get("planner_rms_V"),
        },
        {
            "key": "planner_v_violations",
            "label": "Planner V-limit violations",
            "value": kpis.get("planner_v_violations"),
            "tone": "fail" if (kpis.get("planner_v_violations") or 0) else "",
        },
        {
            "key": "efit_ok",
            "label": "EFIT archive ok",
            "value": kpis.get("efit_ok"),
            "tone": status_tone(kpis.get("efit_ok")),
        },
        {
            "key": "blocking_n",
            "label": "Blocking errors",
            "value": kpis.get("blocking_n"),
            "tone": "fail" if (kpis.get("blocking_n") or 0) else "",
        },
    ]


def kpi_scorecard_table(kpis: Dict[str, Any]) -> Any:
    html, _, dbc = require()
    rows = []
    for r in kpi_scorecard_rows(kpis):
        tone = r.get("tone") or ""
        val_cls = "fg-kpi-val" + (f" fg-kpi-{tone}" if tone else "")
        rows.append(
            html.Tr(
                [
                    html.Td(r["label"], className="fg-kpi-label"),
                    html.Td(fmt_kpi(r.get("value")), className=val_cls),
                ]
            )
        )
    return dbc.Table(
        [
            html.Thead(html.Tr([html.Th("KPI"), html.Th("Value")])),
            html.Tbody(rows),
        ],
        bordered=False,
        hover=True,
        size="sm",
        responsive=True,
        className="fg-scorecard",
    )


def enrich_library_options(
    runs_dir: Any,
    library_options: List[Dict[str, Any]],
    *,
    overview_kpis_fn: Any,
    run_dir_for_fn: Any,
) -> List[Dict[str, Any]]:
    """Add status / blocking count to dropdown labels."""
    out: List[Dict[str, Any]] = []
    from pathlib import Path

    for opt in library_options:
        try:
            shot = int(opt.get("value"))
        except (TypeError, ValueError):
            out.append(dict(opt))
            continue
        run = run_dir_for_fn(Path(runs_dir), shot)
        if run.is_dir():
            k = overview_kpis_fn(run)
            status = k.get("status") or "unknown"
            n_block = k.get("blocking_n")
            label = f"{shot}  ·  {status}"
            if isinstance(n_block, int) and n_block > 0:
                label = f"{label}  ·  {n_block} block"
        else:
            label = f"{shot}  ·  missing"
        out.append({"label": label, "value": shot})
    return out
