"""
Deterministic artifact replayer/verifier (v8.0.0).

Modes:
- strict: requires environment fingerprint match (python/platform)
- relaxed: records env diff but does not fail if artifacts verify

Verification sources (priority):
1) run provenance: provenance/file_hashes.json
2) pack manifest: pack_manifest.json (files list with sha256)
3) fallback: hash_tree of directory

© 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import platform
import sys

from ..util import sha256_file, write_json
from ..provenance import hash_tree, env_fingerprint
from .schema import ReplayReport, ReplayCheck


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _env_diff(declared: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    keys = sorted(set(declared.keys()) | set(current.keys()))
    diff: Dict[str, Any] = {}
    for k in keys:
        if declared.get(k) != current.get(k):
            diff[k] = {"declared": declared.get(k), "current": current.get(k)}
    return diff


def _categorize(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("provenance/") or p == "manifest.json" or p.endswith("repo_state.json"):
        return "CODE_ENV_PROVENANCE"
    if p.startswith("contracts/") or "coil" in p.lower() or "contract" in p.lower():
        return "CONTRACTS"
    if p.startswith("machine_authority_snapshot") or p.startswith("machine_authority"):
        return "MACHINE_AUTHORITY"
    if p.startswith("robustness_v4/") or p.startswith("robustness/") or p.startswith("physics_audit") or p.startswith("model_form"):
        return "AUDITS"
    return "DATA_OUTPUT"


def _load_hash_map(target: Path) -> Tuple[Dict[str, str], Optional[Dict[str, Any]]]:
    """Return (path->sha256, env_fingerprint_declared_if_any)."""
    target = Path(target)

    prov_hash = target / "provenance" / "file_hashes.json"
    prov_env = target / "provenance" / "env_fingerprint.json"
    if prov_hash.exists():
        obj = _read_json(prov_hash)
        sha = obj.get("sha256") if isinstance(obj, dict) else None
        if isinstance(sha, dict):
            env = _read_json(prov_env) if prov_env.exists() else None
            return {str(k): str(v) for k, v in sha.items()}, env

    pack_manifest = target / "pack_manifest.json"
    if pack_manifest.exists():
        obj = _read_json(pack_manifest)
        files = obj.get("files", [])
        m: Dict[str, str] = {}
        if isinstance(files, list):
            for it in files:
                if isinstance(it, dict) and it.get("path") and it.get("sha256"):
                    m[str(it["path"]).replace("\\", "/")] = str(it["sha256"])
        return m, None

    # fallback: hash tree of target
    ht = hash_tree(target)
    return {str(k): str(v) for k, v in ht.get("sha256", {}).items()}, None


def replay_run(target: Path, mode: str = "strict", out_dir: Optional[Path] = None) -> ReplayReport:
    target = Path(target)
    mode = str(mode).lower().strip()
    if mode not in ("strict", "relaxed"):
        raise ValueError("mode must be 'strict' or 'relaxed'")

    m, declared_env = _load_hash_map(target)
    checks: List[ReplayCheck] = []
    n_missing = 0
    n_mismatch = 0

    for rel in sorted(m.keys()):
        exp = m[rel]
        p = target / rel
        if not p.exists():
            n_missing += 1
            checks.append(ReplayCheck(path=rel, expected_sha256=exp, actual_sha256=None, ok=False, category=_categorize(rel), note="missing"))
            continue
        act = sha256_file(p)
        ok = (act == exp)
        if not ok:
            n_mismatch += 1
        checks.append(ReplayCheck(path=rel, expected_sha256=exp, actual_sha256=act, ok=ok, category=_categorize(rel)))

    current_env = env_fingerprint()
    env_match = None
    env_diff = None
    if declared_env is not None:
        # compare stable keys only (exclude created_utc)
        decl = dict(declared_env)
        decl.pop("created_utc", None)
        cur = dict(current_env)
        cur.pop("created_utc", None)
        env_diff = _env_diff(decl, cur)
        env_match = (len(env_diff) == 0)

    ok = (n_missing == 0 and n_mismatch == 0)
    if mode == "strict" and env_match is False:
        ok = False

    report = ReplayReport(
        schema_version="v8.0.0",
        target=str(target),
        mode=mode,
        ok=ok,
        n_files=int(len(m)),
        n_mismatch=int(n_mismatch),
        n_missing=int(n_missing),
        env_match=env_match,
        env_diff=env_diff,
        checks=checks,
    )

    # write outputs
    if out_dir is None:
        out_dir = target / "replay"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "REPLAY_REPORT.json", report.to_dict())
    # minimal markdown
    md = []
    md.append("# REPLAY REPORT\n\n")
    md.append(f"Target: `{report.target}`\n\n")
    md.append(f"Mode: `{report.mode}`\n\n")
    md.append(f"OK: **{report.ok}**\n\n")
    md.append(f"Files: {report.n_files}  Missing: {report.n_missing}  Mismatch: {report.n_mismatch}\n\n")
    if report.env_match is not None:
        md.append(f"Environment match: **{report.env_match}**\n\n")
    (out_dir / "REPLAY_REPORT.md").write_text("".join(md), encoding="utf-8")

    return report
