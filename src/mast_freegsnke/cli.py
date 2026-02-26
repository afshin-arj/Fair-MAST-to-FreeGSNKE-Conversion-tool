
from __future__ import annotations

import argparse
import json
import importlib
import shutil
from pathlib import Path
from typing import Optional

from .availability import check_groups
from .config import AppConfig
from .download import BulkDownloader
from .mastapp import MastAppClient
from .pipeline import ShotPipeline
from .probe_geometry import build_geometry_from_machine_dir, write_geometry_templates, smoke_test_geometry
from .diagnostic_contracts import load_contracts, validate_contracts
from .coil_map import load_coil_map, validate_coil_map
from .machine_authority import machine_authority_from_dir, snapshot_machine_authority
from .reviewer_pack import build_reviewer_pack
from .robustness.orchestrator import robustness_run
from .robustness.reviewer_pack import build_robustness_reviewer_pack
from .corpus.corpus_build import build_corpus
from .corpus.atlas import build_atlas
from .corpus.compare import compare_atlases
from .corpus.regression_guard import regression_guard
from .physics_audit.schema import PhysicsAuditConfig
from .physics_audit.audit import run_physics_audit
from .physics_audit.pack import build_physics_audit_pack
from .physics_audit.plots import make_plots as make_physics_plots
from .corpus.closure_atlas import build_closure_atlas
from .model_form.schema import ModelFormConfig
from .model_form.mfe import run_model_form_audit
from .model_form.splits import generate_cv_splits
from .model_form.forward import run_forward_checks
from .model_form.pack import build_consistency_triangle_pack
from .replay.replayer import replay_run
from .replay.nondeterminism import nondeterminism_check
from .forensics.compare import forensic_compare



def _has(pkg: str) -> bool:
    return importlib.util.find_spec(pkg) is not None


def _opt_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    return float(x)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="mast-freegsnke",
        description="MAST shot -> download -> generate FreeGSNKE scripts",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Check environment prerequisites")
    d.add_argument("--config", type=str, required=True)

    c = sub.add_parser("check", help="Check availability of required Level-2 groups (no download)")
    c.add_argument("--shot", type=int, required=True)
    c.add_argument("--config", type=str, required=True)

    wcmd = sub.add_parser("window", help="Infer formed-plasma time window from run inputs")
    wcmd.add_argument("--shot", type=int, required=True)
    wcmd.add_argument("--config", type=str, required=True)

    qcmd = sub.add_parser("windowqc", help="Compute QC diagnostics for inferred time window (requires prior run)")
    qcmd.add_argument("--shot", type=int, required=True)
    qcmd.add_argument("--config", type=str, required=True)

    kcmd = sub.add_parser("consensus", help="Compute multi-signal time window consensus (requires prior run inputs)")
    kcmd.add_argument("--shot", type=int, required=True)
    kcmd.add_argument("--config", type=str, required=True)

    gtmpl = sub.add_parser("geom-template", help="Write probe geometry template files into a machine directory")
    gtmpl.add_argument("--machine", type=str, required=True)

    gval = sub.add_parser("geom-validate", help="Validate probe geometry resolution from a machine directory")
    gval.add_argument("--machine", type=str, required=True)

    gsmk = sub.add_parser("geom-smoke", help="Run a lightweight synthetic diagnostics smoke test on resolved probe geometry")
    gsmk.add_argument("--machine", type=str, required=True)

    cv = sub.add_parser("contracts-validate", help="Validate diagnostic contracts JSON")
    cv.add_argument("--contracts", type=str, required=True)
    cv.add_argument("--require-files", action="store_true", help="Require that referenced CSV files exist")

    mv = sub.add_parser("coilmap-validate", help="Validate PF/coil mapping JSON")
    mv.add_argument("--coil-map", type=str, required=True)


    mav = sub.add_parser("machine-validate", help="Validate and (optionally) snapshot machine authority directory")
    mav.add_argument("--machine-authority", type=str, required=True)
    mav.add_argument("--snapshot-to", type=str, default=None, help="If set, copy authority into this run directory's machine_authority_snapshot/")

    rp = sub.add_parser("reviewer-pack", help="Build a self-contained reviewer pack for a completed run")

    rr = sub.add_parser("robustness-run", help="Run v4 multi-window robustness (DOE + stability) inside an existing run directory")
    rr.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")
    rr.add_argument("--policy", type=str, default="maximin", help="Robust selection policy: maximin|quantile75")
    rr.add_argument("--green", type=float, default=0.05, help="GREEN relative degradation threshold")
    rr.add_argument("--yellow", type=float, default=0.15, help="YELLOW relative degradation threshold")
    rr.add_argument("--allow-sign-toggle", action="store_true", help="Enable explicit sign-toggle perturbation scenarios (default off)")

    rp2 = sub.add_parser("robustness-pack", help="Build robustness reviewer pack (requires prior robustness-run)")
    rp2.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")
    rp2.add_argument("--out", type=str, default=None, help="Optional output directory (defaults to <run>/robustness_v4/ROBUSTNESS_REVIEWER_PACK)")


    pa = sub.add_parser("physics-audit-run", help="Run v6 physics-consistency audit inside an existing run directory (requires robustness_v4)")
    pa.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")
    pa.add_argument("--primary-metric", type=str, default="score_total", help="Primary metric key from robust choice (default score_total)")
    pa.add_argument("--green", type=float, default=0.05, help="PHYSICS-GREEN threshold for normalized violation")
    pa.add_argument("--yellow", type=float, default=0.15, help="PHYSICS-YELLOW threshold for normalized violation")
    pa.add_argument("--plots", action="store_true", help="Generate deterministic physics-audit plots + hashed manifest")

    pp = sub.add_parser("physics-audit-pack", help="Build physics-audit reviewer pack (requires prior physics-audit-run)")
    pp.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")

    ca = sub.add_parser("closure-atlas-build", help="Build a corpus-level closure atlas from physics-audit outputs (v6)")
    ca.add_argument("--corpus", type=str, required=True, help="Corpus directory produced by corpus-build")
    ca.add_argument("--out", type=str, default=None, help="Optional output directory (default <corpus>/atlas/closure_atlas)")


    fc = sub.add_parser("forward-check-run", help="Run deterministic forward checks (v7) using existing scenario outputs")
    fc.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")
    fc.add_argument("--primary-metric", type=str, default="score_total", help="Metric key to evaluate (default score_total)")

    mf = sub.add_parser("model-form-run", help="Run model-form audit: deterministic CV splits + forward checks + MFE tier (v7)")
    mf.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")
    mf.add_argument("--primary-metric", type=str, default="score_total", help="Metric key to evaluate (default score_total)")
    mf.add_argument("--green", type=float, default=0.05, help="MFE-GREEN threshold for worst relative degradation")
    mf.add_argument("--yellow", type=float, default=0.15, help="MFE-YELLOW threshold for worst relative degradation")
    mf.add_argument("--max-splits", type=int, default=64, help="Maximum number of deterministic CV splits")

    cp = sub.add_parser("consistency-pack", help="Build Consistency Triangle reviewer pack (robustness + physics + model-form)")
    cp.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")


    rr = sub.add_parser("replay-run", help="Verify run/pack artifacts against their declared hashes (v8)")
    rr.add_argument("--target", type=str, required=True, help="Run directory or exported pack directory")
    rr.add_argument("--mode", type=str, default="strict", choices=["strict","relaxed"], help="Env closure mode")

    fp = sub.add_parser("forensic-compare", help="Forensic compare two runs/packs (v8)")
    fp.add_argument("--A", type=str, required=True, help="Run or pack path A")
    fp.add_argument("--B", type=str, required=True, help="Run or pack path B")
    fp.add_argument("--out", type=str, default=None, help="Optional output directory (default ./forensics)")

    nd = sub.add_parser("nondeterminism-check", help="Check replay hashing stability N times (v8)")
    nd.add_argument("--target", type=str, required=True, help="Run directory or pack directory")
    nd.add_argument("--n", type=int, default=3, help="Number of repeats (>=2)")
    rp.add_argument("--run", type=str, required=True, help="Run directory, e.g. runs/shot_30201")
    rp.add_argument("--out", type=str, default=None, help="Optional output directory (defaults to <run>/REVIEWER_PACK)")

    
    cb = sub.add_parser("corpus-build", help="Build a deterministic corpus index from completed run directories (v5)")
    cb.add_argument("--runs", type=str, nargs="+", required=True, help="One or more run directories, e.g. runs/shot_30201")
    cb.add_argument("--out", type=str, required=True, help="Output directory for corpus artifacts")
    cb.add_argument("--robustness-subdir", type=str, default="robustness_v4", help="Robustness artifact directory name inside each run (default robustness_v4)")

    ab = sub.add_parser("atlas-build", help="Build a cross-shot robustness atlas from a corpus (v5)")
    ab.add_argument("--corpus", type=str, required=True, help="Corpus directory produced by corpus-build")
    ab.add_argument("--out", type=str, default=None, help="Optional atlas output directory (default <corpus>/atlas)")

    cr = sub.add_parser("compare-run", help="Compare two atlas directories (A/B) and produce certified deltas (v5)")
    cr.add_argument("--A", type=str, required=True, help="Atlas directory A (contains atlas_metrics.csv)")
    cr.add_argument("--B", type=str, required=True, help="Atlas directory B (contains atlas_metrics.csv)")
    cr.add_argument("--out", type=str, required=True, help="Output directory for comparator artifacts")

    rg = sub.add_parser("regression-guard", help="Apply deterministic regression guard to a compare-run output (v5)")
    rg.add_argument("--delta", type=str, required=True, help="Path to delta_scorecards.json from compare-run")
    rg.add_argument("--out", type=str, required=True, help="Output path for regression_guard.json")
    rg.add_argument("--max-red-increase", type=int, default=0, help="Maximum allowed increase in RED tier count (default 0)")
    rg.add_argument("--max-median-degradation-increase", type=float, default=0.0, help="Maximum allowed increase in median relative degradation (default 0.0)")
    rg.add_argument("--max-physics-red-increase", type=int, default=0, help="Maximum allowed increase in PHYSICS-RED tier count (default 0)")
    rg.add_argument("--max-physics-median-violation-increase", type=float, default=0.0, help="Maximum allowed increase in median physics max-violation (default 0.0)")
    rg.add_argument("--max-mfe-red-increase", type=int, default=0, help="Maximum allowed increase in MFE-RED tier count (default 0)")
    rg.add_argument("--max-mfe-median-worst-rel-deg-increase", type=float, default=0.0, help="Maximum allowed increase in median MFE worst-relative-degradation (default 0.0)")

    r = sub.add_parser("run", help="Run pipeline for a shot")
    r.add_argument("--shot", type=int, required=True)
    r.add_argument("--config", type=str, required=True)
    r.add_argument("--machine", type=str, required=True)
    r.add_argument("--tstart", type=float, default=None, help="Deterministic window override start time [s]")
    r.add_argument("--tend", type=float, default=None, help="Deterministic window override end time [s]")
    r.add_argument("--execute-freegsnke", action="store_true", help="Execute generated FreeGSNKE scripts (requires freegsnke in selected python)")
    r.add_argument("--freegsnke-mode", type=str, default=None, help="Override config freegsnke_run_mode: none|inverse|forward|both")
    r.add_argument("--freegsnke-python", type=str, default=None, help="Override config freegsnke_python (path to python exe in FreeGSNKE env)")
    r.add_argument("--contracts", type=str, default=None, help="Override config diagnostic_contracts_path")
    r.add_argument("--coil-map", type=str, default=None, help="Override config coil_map_path")
    r.add_argument("--enable-contract-metrics", action="store_true", help="Enable contract-driven synthetic extraction and residual scoring")


    args = ap.parse_args(argv)

    cfg = None
    templates_dir = Path(__file__).resolve().parents[2] / "templates"
    if hasattr(args, "config") and getattr(args, "config") is not None:
        cfg = AppConfig.load(Path(args.config))

    if args.cmd == "doctor":
        ok = True
        if shutil.which(cfg.s5cmd_path) is None:
            print(f"[FAIL] s5cmd not found: {cfg.s5cmd_path}")
            ok = False
        else:
            print(f"[OK] s5cmd: {cfg.s5cmd_path}")

        if not cfg.level2_s3_prefix or "CHANGE_ME" in cfg.level2_s3_prefix:
            print("[FAIL] level2_s3_prefix not set in config.json")
            ok = False
        else:
            print("[OK] level2_s3_prefix set")

        if _has("xarray") and _has("pandas") and _has("zarr") and _has("numpy"):
            print("[OK] optional zarr stack installed (extraction enabled)")
        else:
            print("[WARN] optional zarr stack missing (extraction will be skipped). Install: pip install -e '.[zarr]'")
        return 0 if ok else 2


    if args.cmd == "corpus-build":
        out = build_corpus(
            run_dirs=[Path(p) for p in args.runs],
            out_dir=Path(args.out),
            robustness_subdir=args.robustness_subdir,
        )
        print(str(out))
        return 0

    if args.cmd == "atlas-build":
        out = build_atlas(corpus_dir=Path(args.corpus), out_dir=Path(args.out) if args.out else None)
        print(str(out))
        return 0

    if args.cmd == "compare-run":
        out = compare_atlases(atlas_a=Path(args.A), atlas_b=Path(args.B), out_dir=Path(args.out))
        print(str(out))
        return 0

    if args.cmd == "regression-guard":
        out = regression_guard(
            delta_scorecards_path=Path(args.delta),
            out_path=Path(args.out),
            max_red_increase=args.max_red_increase,
            max_median_degradation_increase=args.max_median_degradation_increase,
        )
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if out.get("ok") else 6

    if args.cmd == "check":
        client = MastAppClient(base_url=cfg.mastapp_base_url)
        if not client.shot_exists(args.shot):
            print(f"[FAIL] Shot {args.shot} not available via MastApp REST at {cfg.mastapp_base_url}")
            return 3

        dl = BulkDownloader(
            s5cmd_path=cfg.s5cmd_path,
            level2_s3_prefix=cfg.level2_s3_prefix,
            layout_patterns=cfg.s3_layout_patterns,
        )
        avail = check_groups(shot=args.shot, groups=cfg.required_groups, discover=dl.discover_group_path)

        ok = True
        for g, v in avail.items():
            if v.exists:
                print(f"[OK] {g}: {v.s3_path}")
            else:
                print(f"[MISSING] {g}: {v.error}")
                ok = False
        return 0 if ok else 4

    if args.cmd == "window":
        from .util import write_json
        from .windowing import infer_time_window

        run_inputs = Path(cfg.runs_dir) / f"shot_{args.shot}" / "inputs"
        if not run_inputs.exists():
            print(f"[FAIL] Missing run inputs folder: {run_inputs}. Run pipeline first.")
            return 5
        try:
            tw = infer_time_window(inputs_dir=run_inputs, formed_frac=cfg.formed_plasma_frac)
            write_json(run_inputs / "window.json", tw.__dict__)
            print(f"[OK] window: {tw.t_start} .. {tw.t_end} (source={tw.source}, signal={tw.signal_column})")
            return 0
        except Exception as e:
            print(f"[FAIL] window inference error: {e}")
            return 6

    if args.cmd == "windowqc":
        from .util import write_json
        from .windowing import infer_time_window
        from .window_quality import evaluate_time_window, format_diagnostics

        run_inputs = Path(cfg.runs_dir) / f"shot_{args.shot}" / "inputs"
        if not run_inputs.exists():
            print(f"[FAIL] Missing run inputs folder: {run_inputs}. Run pipeline first.")
            return 7
        try:
            tw = infer_time_window(inputs_dir=run_inputs, formed_frac=cfg.formed_plasma_frac)
            write_json(run_inputs / "window.json", tw.__dict__)
            diag = evaluate_time_window(inputs_dir=run_inputs, tw=tw)
            write_json(run_inputs / "window_diagnostics.json", diag.__dict__)
            (run_inputs / "WINDOW_QC_REPORT.txt").write_text(format_diagnostics(diag))
            print(f"[OK] QC confidence={diag.confidence} flags={diag.flags}")
            return 0
        except Exception as e:
            print(f"[FAIL] windowqc error: {e}")
            return 8

    
    if args.cmd == "geom-template":
        try:
            out = write_geometry_templates(Path(args.machine))
            print("[OK] wrote geometry templates:")
            for k, v in out.items():
                print(f"  - {k}: {v}")
            return 0
        except Exception as e:
            print(f"[FAIL] geom-template error: {e}")
            return 30

    if args.cmd == "geom-validate":
        try:
            geom, rep = build_geometry_from_machine_dir(Path(args.machine))
            # Always print report summary
            print(f"[INFO] geometry status={rep.get('status')} source={rep.get('source')}")
            if geom is None:
                print("[FAIL] geometry not resolved/valid. See errors:")
                for er in rep.get("errors", []):
                    print(f"  - {er}")
                return 31
            print(f"[OK] geometry resolved: n_flux_loops={len(geom.flux_loops)} n_pickup_coils={len(geom.pickup_coils)}")
            return 0
        except Exception as e:
            print(f"[FAIL] geom-validate error: {e}")
            return 32

    if args.cmd == "geom-smoke":
        try:
            geom, rep = build_geometry_from_machine_dir(Path(args.machine))
            if geom is None:
                print(f"[FAIL] geometry not resolved/valid (status={rep.get('status')}).")
                for er in rep.get("errors", []):
                    print(f"  - {er}")
                return 33
            srep = smoke_test_geometry(geom)
            print(f"[INFO] smoke status={srep.get('status')}")
            if srep.get("errors"):
                print("[FAIL] smoke errors:")
                for er in srep["errors"]:
                    print(f"  - {er}")
                return 34
            print("[OK] smoke test passed.")
            return 0
        except Exception as e:
            print(f"[FAIL] geom-smoke error: {e}")
            return 35

    if args.cmd == "contracts-validate":
        try:
            contracts = load_contracts(Path(args.contracts), base_dir=Path(args.contracts).parent)
            rep = validate_contracts(contracts, require_files=bool(args.require_files))
            print(f"[INFO] contracts ok={rep.get('ok')} n={rep.get('n_contracts')}")
            if not rep.get("ok", False):
                for er in rep.get("errors", []):
                    print(f"  - {er}")
                return 40
            return 0
        except Exception as e:
            print(f"[FAIL] contracts-validate error: {e}")
            return 41
    
    if args.cmd == "coilmap-validate":
        try:
            cm = load_coil_map(Path(args.coil_map))
            rep = validate_coil_map(cm)
            print(f"[INFO] coil_map ok={rep.get('ok')} n={rep.get('n')}")
            if not rep.get("ok", False):
                for er in rep.get("errors", []):
                    print(f"  - {er}")
                return 42
            return 0
        except Exception as e:
            print(f"[FAIL] coilmap-validate error: {e}")
            return 43
    
    if args.cmd == "machine-validate":
        try:
            ma_root = Path(args.machine_authority)
            ma, rep = machine_authority_from_dir(ma_root)
            print(f"[INFO] machine_authority ok={rep.get('ok')} root={rep.get('root')}")
            if ma is None:
                for er in rep.get("errors", []):
                    print(f"  - {er}")
                return 44
            if args.snapshot_to:
                run_dir = Path(args.snapshot_to)
                snap = snapshot_machine_authority(ma, run_dir=run_dir)
                print(f"[OK] snapshot written to: {run_dir / 'machine_authority_snapshot'}")
                print(f"      authority={snap.get('authority_name')} version={snap.get('authority_version')}")
            return 0
        except Exception as e:
            print(f"[FAIL] machine-validate error: {e}")
            return 45
    
    if args.cmd == "reviewer-pack":
        try:
            run_dir = Path(args.run)
            out_dir = Path(args.out) if args.out else None
            rep = build_reviewer_pack(run_dir=run_dir, out_dir=out_dir)
            print(f"[OK] reviewer pack: {rep.get('out_dir')}")
            if rep.get("missing"):
                print("[WARN] missing items:")
                for m in rep["missing"]:
                    print(f"  - {m}")
            return 0

        except Exception as e:
            print(f"[FAIL] reviewer-pack error: {e}")
            return 46


    if args.cmd == "robustness-run":
        out_root = robustness_run(
            run_dir=Path(args.run),
            policy=str(args.policy),
            green=float(args.green),
            yellow=float(args.yellow),
            allow_sign_toggle=bool(args.allow_sign_toggle),
        )
        print(json.dumps({"ok": True, "robustness_dir": str(out_root)}, indent=2))
        return 0

    if args.cmd == "robustness-pack":
        out = build_robustness_reviewer_pack(
            run_dir=Path(args.run),
            out_dir=Path(args.out) if args.out else None,
        )
        print(json.dumps({"ok": True, "robustness_pack": str(out)}, indent=2))
        return 0

    if args.cmd == "consensus":
        from .util import write_json
        from .window_consensus import infer_consensus_window

        run_inputs = Path(cfg.runs_dir) / f"shot_{args.shot}" / "inputs"
        if not run_inputs.exists():
            print(f"[FAIL] Missing run inputs folder: {run_inputs}. Run pipeline first.")
            return 9
        try:
            cw = infer_consensus_window(inputs_dir=run_inputs, formed_frac=cfg.formed_plasma_frac)
            write_json(run_inputs / "window_consensus.json", cw.__dict__)
            print(f"[OK] consensus: {cw.t_start} .. {cw.t_end} (frac_agree={cw.frac_sources_agree}, sources={cw.sources_used})")
            return 0
        except Exception as e:
            print(f"[FAIL] consensus error: {e}")
            return 10


    elif args.cmd == "physics-audit-run":
        run_dir = Path(args.run).resolve()
        cfg_pa = PhysicsAuditConfig(
            physics_green=float(args.green),
            physics_yellow=float(args.yellow),
            primary_metric=str(args.primary_metric),
            zero_timestamp_mode=True,
        )
        sc = run_physics_audit(run_dir, cfg_pa)
        # optional plots
        phys_dir = run_dir / "robustness_v4" / "physics_audit"
        if args.plots:
            make_physics_plots(phys_dir)
        print(f"[OK] physics audit tier: {sc.tier}  max_violation={sc.max_violation}")
        return 0

    elif args.cmd == "physics-audit-pack":
        run_dir = Path(args.run).resolve()
        pack_dir = build_physics_audit_pack(run_dir)
        print(f"[OK] physics audit pack: {pack_dir}")
        return 0

    elif args.cmd == "closure-atlas-build":
        corpus_dir = Path(args.corpus).resolve()
        out_dir = Path(args.out).resolve() if args.out is not None else None
        out = build_closure_atlas(corpus_dir, out=out_dir)
        print(f"[OK] closure atlas: {out}")
        return 0


    elif args.cmd == "forward-check-run":
        run_dir = Path(args.run).resolve()
        splits = generate_cv_splits(run_dir, max_splits=64)
        df = run_forward_checks(run_dir, splits, primary_metric=str(args.primary_metric))
        out_dir = run_dir / "robustness_v4" / "model_form"
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_dir / "forward_checks.csv", index=False)
        (out_dir / "cv_splits.json").write_text(json.dumps({"schema_version":"v7.0.0","splits":[s.to_dict() for s in splits]}, indent=2, sort_keys=True))
        print(f"[OK] forward checks written: {out_dir}")
        return 0

    elif args.cmd == "model-form-run":
        run_dir = Path(args.run).resolve()
        cfg_mf = ModelFormConfig(
            mfe_green=float(args.green),
            mfe_yellow=float(args.yellow),
            primary_metric=str(args.primary_metric),
            max_splits=int(args.max_splits),
            zero_timestamp_mode=True,
        )
        sc = run_model_form_audit(run_dir, cfg_mf)
        print(f"[OK] model-form tier: {sc.tier}  worst_relative_degradation={sc.worst_relative_degradation}")
        return 0

    elif args.cmd == "consistency-pack":
        run_dir = Path(args.run).resolve()
        pack = build_consistency_triangle_pack(run_dir)
        print(f"[OK] consistency triangle pack: {pack}")
        return 0


    elif args.cmd == "replay-run":
        target = Path(args.target).resolve()
        rep = replay_run(target, mode=str(args.mode))
        print(f"[OK] replay ok={rep.ok} missing={rep.n_missing} mismatch={rep.n_mismatch} env_match={rep.env_match}")
        return 0 if rep.ok else 12

    elif args.cmd == "forensic-compare":
        A = Path(args.A).resolve()
        B = Path(args.B).resolve()
        out = Path(args.out).resolve() if args.out is not None else (Path.cwd() / "forensics")
        delta = forensic_compare(A, B, out_dir=out)
        print(f"[OK] forensic ok={delta.ok} divergence_class={delta.divergence_class} out={out}")
        return 0 if delta.ok else 13

    elif args.cmd == "nondeterminism-check":
        target = Path(args.target).resolve()
        rep = nondeterminism_check(target, n=int(args.n))
        print(f"[OK] nondeterminism ok={rep.ok} hashes={rep.run_hashes}")
        return 0 if rep.ok else 14

    if args.cmd == "run":
        # CLI overrides (kept deterministic and explicit): these override config for this invocation only.
        if args.execute_freegsnke:
            object.__setattr__(cfg, "execute_freegsnke", True)
        if args.freegsnke_mode is not None:
            object.__setattr__(cfg, "freegsnke_run_mode", str(args.freegsnke_mode).lower())
        if args.freegsnke_python is not None:
            object.__setattr__(cfg, "freegsnke_python", str(args.freegsnke_python))

        if args.contracts is not None:
            object.__setattr__(cfg, "diagnostic_contracts_path", str(args.contracts))
        if args.coil_map is not None:
            object.__setattr__(cfg, "coil_map_path", str(args.coil_map))
        if args.enable_contract_metrics:
            object.__setattr__(cfg, "enable_contract_metrics", True)

        pipe = ShotPipeline(cfg=cfg, templates_dir=templates_dir)
        try:
            run_dir = pipe.run(
                shot=args.shot,
                machine_dir=Path(args.machine),
                tstart=args.tstart,
                tend=args.tend,
            )
            print(f"[OK] Run folder: {run_dir}")
            return 0
        except Exception as e:
            print(f"[FAIL] run error: {e}")
            # manifest should exist in run folder
            return 11

    return 1
