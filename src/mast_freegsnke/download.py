from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple
import shutil
import subprocess
import json

from .util import run_cmd, looks_like_exists_s5cmd_ls, resolve_s5cmd_path, shot_cache_dir


def group_cache_stats(shot_dir: Path, group: str) -> Tuple[int, int]:
    """Cheap per-group cache stats: (n_files, total_bytes). No hashing."""
    dst = Path(shot_dir) / f"{group}.zarr"
    if not dst.is_dir():
        return 0, 0
    n = 0
    total = 0
    for p in dst.rglob("*"):
        if p.is_file():
            n += 1
            total += p.stat().st_size
    return n, total


def group_cache_hit(shot_dir: Path, group: str) -> bool:
    """True when data_cache/shot_<N>/<group>.zarr exists and contains at least one file."""
    dst = Path(shot_dir) / f"{group}.zarr"
    if not dst.is_dir():
        return False
    return any(p.is_file() for p in dst.rglob("*"))


def load_prior_resolved_paths(shot_dir: Path) -> Dict[str, str]:
    """Read resolved_s3_paths.json written by an earlier download (empty dict if absent/invalid)."""
    p = Path(shot_dir) / "resolved_s3_paths.json"
    if not p.exists():
        return {}
    try:
        obj = json.loads(p.read_text())
        return {str(k): str(v) for k, v in obj.items()} if isinstance(obj, dict) else {}
    except Exception:
        return {}


def build_cache_report(shot_dir: Path, groups: List[str]) -> Dict[str, Dict[str, Any]]:
    """Per-group provenance for cached groups: resolved S3 path (if previously recorded),
    cache_hit flag, and cheap file counts/bytes. Never hashes the Zarr tree."""
    prior = load_prior_resolved_paths(shot_dir)
    report: Dict[str, Dict[str, Any]] = {}
    for g in groups:
        n_files, total_bytes = group_cache_stats(shot_dir, g)
        report[g] = {
            "s3_path": prior.get(g),
            "cache_hit": True,
            "n_files": n_files,
            "total_bytes": total_bytes,
        }
    return report

@dataclass
class BulkDownloader:
    s5cmd_path: str
    level2_s3_prefix: str
    layout_patterns: List[str]
    s3_endpoint_url: str | None = None
    s3_no_sign_request: bool = False
    timeout_s: int = 60

    def _check_s5cmd(self) -> None:
        resolved = resolve_s5cmd_path(self.s5cmd_path)
        p = Path(resolved)
        if p.is_file() or shutil.which(resolved) is not None:
            self.s5cmd_path = resolved
            return
        raise RuntimeError(
            f"s5cmd not found: '{self.s5cmd_path}'. Install s5cmd or place it at tools/s5cmd.exe."
        )


    def _s5cmd_base(self) -> List[str]:
        cmd: List[str] = [self.s5cmd_path]
        if self.s3_no_sign_request:
            cmd.append("--no-sign-request")
        if self.s3_endpoint_url:
            cmd += ["--endpoint-url", self.s3_endpoint_url]
        return cmd

    def preflight(self, shot: int | None = None) -> str:
        """Fail-fast transport + layout preflight.

        v10.0.7 verified transport by probing the prefix root, which can be extremely slow for large
        archives (e.g. listing all shots). v10.0.8 makes this *shot-scoped*:

        - If `shot` is provided, we probe only candidate shot-root paths derived from the configured
          `layout_patterns` (O(N_patterns)).
        - If `shot` is None, we probe only the prefix itself (still bounded by timeout), but we do
          not enumerate large subtrees.

        Returns
        -------
        resolved_shot_root:
            The first discovered shot-root candidate (only meaningful when `shot` is provided).
        """
        self._check_s5cmd()
        if not self.level2_s3_prefix or "CHANGE_ME" in self.level2_s3_prefix:
            raise RuntimeError("Config 'level2_s3_prefix' is not set. Edit configs/default.json.")

        base = self.level2_s3_prefix.rstrip("/")

        def _probe(path: str) -> tuple[int, str]:
            probe = path.rstrip("/") + "/"
            return run_cmd(self._s5cmd_base() + ["ls", probe], timeout_s=self.timeout_s)

        if shot is not None:
            tried: List[Dict[str, object]] = []
            roots: List[str] = []
            for pat in self.layout_patterns:
                if "{group}" not in pat:
                    continue
                root_pat = pat.split("{group}", 1)[0].rstrip("/")
                try:
                    root = root_pat.format(prefix=base, shot=shot, group="")
                except Exception:
                    continue
                root = root.rstrip("/")
                if root and root not in roots:
                    roots.append(root)

            # Fallback: canonical MAST layout is {prefix}/{shot}.zarr/{group}/...
            if not roots:
                roots = [f"{base}/{shot}.zarr"]

            for root in roots:
                rc, out = _probe(root)
                tried.append({"candidate": root.rstrip("/") + "/", "rc": int(rc)})
                if rc == 0 and looks_like_exists_s5cmd_ls(out):
                    return root

            msg = "S3 shot-scoped preflight failed. Could not locate shot root.\n"
            msg += f"shot: {shot}\n"
            msg += f"prefix: {self.level2_s3_prefix}\n"
            msg += "tried shot-root candidates:\n"
            for t in tried:
                msg += f"  - {t['candidate']} (rc={t['rc']})\n"
            msg += (
                "\n"
                "hint: for public MAST Level-2, set "
                "level2_s3_prefix=s3://mast/level2/shots, "
                "s3_endpoint_url=https://s3.echo.stfc.ac.uk, "
                "s3_no_sign_request=true, and use patterns like '{prefix}/{shot}.zarr/{group}'.\n"
            )
            raise RuntimeError(msg)

        rc, out = _probe(base)
        if rc != 0:
            raise RuntimeError(
                "S3 preflight failed (rc={}). Check endpoint/credentials/prefix.\n".format(rc)
                + "prefix: {}\n".format(self.level2_s3_prefix)
                + "hint: for MAST public data, set s3_endpoint_url=https://s3.echo.stfc.ac.uk and s3_no_sign_request=true\n"
                + out
            )
        return base

    def _render_candidates(self, shot: int, group: str) -> List[str]:
        base = self.level2_s3_prefix.rstrip("/")
        return [pat.format(prefix=base, group=group, shot=shot) for pat in self.layout_patterns]

    def discover_group_path(self, shot: int, group: str) -> str:
        self._check_s5cmd()
        if not self.level2_s3_prefix or "CHANGE_ME" in self.level2_s3_prefix:
            raise RuntimeError("Config 'level2_s3_prefix' is not set. Edit configs/config.json.")
        tried = []
        for cand in self._render_candidates(shot, group):
            probe = cand.rstrip("/") + "/"
            rc, out = run_cmd(self._s5cmd_base() + ["ls", probe], timeout_s=self.timeout_s)
            tried.append({"candidate": probe, "rc": rc})
            if rc == 0 and looks_like_exists_s5cmd_ls(out):
                return cand
        msg = f"Could not discover S3 path for group='{group}' shot={shot}. Tried:\n"
        for t in tried:
            msg += f"  - {t['candidate']} (rc={t['rc']})\n"
        raise FileNotFoundError(msg)

    def download_groups(
        self,
        shot: int,
        groups: List[str],
        cache_dir: Path,
        allow_cache_reuse: bool = False,
    ) -> Tuple[Path, Dict[str, Dict[str, Any]]]:
        """Sync required groups into data_cache/shot_<N>/.

        When allow_cache_reuse is True, a group whose <group>.zarr tree already
        exists and is non-empty is not re-synced (cache hit). Every group is
        reported deterministically: resolved S3 path (from discovery, or from
        the prior resolved_s3_paths.json for cache hits), cache_hit flag, and
        cheap file counts/bytes (no tree hashing).
        """
        shot_dir = shot_cache_dir(cache_dir, shot)
        shot_dir.mkdir(parents=True, exist_ok=True)

        prior = load_prior_resolved_paths(shot_dir)
        resolved: Dict[str, str] = dict(prior)
        report: Dict[str, Dict[str, Any]] = {}
        for g in groups:
            dst = shot_dir / f"{g}.zarr"
            if allow_cache_reuse and group_cache_hit(shot_dir, g):
                n_files, total_bytes = group_cache_stats(shot_dir, g)
                report[g] = {
                    "s3_path": prior.get(g),
                    "cache_hit": True,
                    "n_files": n_files,
                    "total_bytes": total_bytes,
                }
                continue

            self._check_s5cmd()
            src = self.discover_group_path(shot, g)
            # discover may return a pattern that already ends with /*; normalize to a directory URI.
            src_dir = src.rstrip("/")
            if src_dir.endswith("/*"):
                src_dir = src_dir[:-2].rstrip("/")
            elif src_dir.endswith("*"):
                src_dir = src_dir[:-1].rstrip("/")
            resolved[g] = src_dir
            dst.mkdir(parents=True, exist_ok=True)
            # s5cmd sync requires a wildcard source to copy object trees into a local directory.
            sync_src = src_dir.rstrip("/") + "/*"
            cmd = self._s5cmd_base() + ["sync", sync_src, str(dst)]
            # Downloads can exceed the short ls timeout; allow a longer bound for sync.
            sync_timeout = max(int(self.timeout_s), 600)
            subprocess.run(cmd, check=True, timeout=sync_timeout)
            if not (dst / "zarr.json").exists() and not any(dst.iterdir()):
                raise RuntimeError(f"s5cmd sync produced empty destination for {g}: {dst} (src={sync_src})")
            n_files, total_bytes = group_cache_stats(shot_dir, g)
            report[g] = {
                "s3_path": src_dir,
                "cache_hit": False,
                "n_files": n_files,
                "total_bytes": total_bytes,
            }

        (shot_dir / "resolved_s3_paths.json").write_text(json.dumps(resolved, indent=2, sort_keys=True) + "\n")
        (shot_dir / "download_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return shot_dir, report
