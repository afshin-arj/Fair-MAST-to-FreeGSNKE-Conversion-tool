"""Provenance hashing must not walk history/ or Windows layout junctions."""
from __future__ import annotations

import json
import os
from pathlib import Path

from mast_freegsnke.pipeline import (
    _archive_prior_run,
    _LAYOUT_SHIM_NAMES,
    _sanitize_history_reparse_points,
)
from mast_freegsnke.provenance import hash_tree, write_provenance


def test_hash_tree_skips_history(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    run.mkdir()
    (run / "manifest.json").write_text("{}", encoding="utf-8")
    hist = run / "history" / "20260101_000000" / "contracts"
    hist.mkdir(parents=True)
    (hist / "secret.bin").write_bytes(b"should-not-hash")
    (run / "inputs").mkdir()
    (run / "inputs" / "ip.csv").write_text("time,ip\n0,1\n", encoding="utf-8")

    out = hash_tree(run)
    paths = set(out["sha256"])
    assert "inputs/ip.csv" in paths or "inputs\\ip.csv" in paths or any(p.endswith("ip.csv") for p in paths)
    assert not any("history" in p.replace("\\", "/") for p in paths)


def test_write_provenance_ok_with_history_junk(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    run.mkdir()
    (run / "inputs").mkdir()
    (run / "inputs" / "a.txt").write_text("x", encoding="utf-8")
    locked = run / "history" / "old" / "contracts"
    locked.mkdir(parents=True)
    (locked / "x.json").write_text("{}", encoding="utf-8")

    summary = write_provenance(run_dir=run, repo_root=tmp_path)
    assert summary["ok"] is True
    assert (run / "provenance" / "file_hashes.json").is_file()
    hashes = json.loads((run / "provenance" / "file_hashes.json").read_text(encoding="utf-8"))
    assert not any("history" in p.replace("\\", "/") for p in hashes.get("sha256", {}))


def test_hash_tree_survives_broken_history_junction(tmp_path: Path, monkeypatch) -> None:
    """Regression: WinError 3 on history/<ts>/contracts during provenance_lock."""
    run = tmp_path / "30201"
    run.mkdir()
    (run / "inputs").mkdir()
    (run / "inputs" / "keep.txt").write_text("ok", encoding="utf-8")
    auth = run / "06_authorities" / "contracts"
    auth.mkdir(parents=True)
    (auth / "coil.json").write_text("{}", encoding="utf-8")

    hist = run / "history" / "20260724_075746"
    hist.mkdir(parents=True)
    shim = hist / "contracts"

    if os.name == "nt":
        import subprocess

        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(shim), str(auth)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            # Fallback: fake reparse detection + broken path walk
            shim.mkdir()
    else:
        shim.symlink_to(auth, target_is_directory=True)

    # Break the target the way a re-run archive does (move live authorities away).
    broken_target = run / "06_authorities"
    broken_target.rename(run / "06_authorities.__away__")

    out = hash_tree(run)
    paths = set(out["sha256"])
    assert any(p.endswith("keep.txt") for p in paths)
    assert not any("history" in p.replace("\\", "/") for p in paths)

    summary = write_provenance(run_dir=run, repo_root=tmp_path)
    assert summary["ok"] is True


def test_sanitize_history_strips_reparse_points(tmp_path: Path, monkeypatch) -> None:
    run = tmp_path / "30201"
    hist = run / "history" / "old"
    hist.mkdir(parents=True)
    shim = hist / "contracts"
    shim.mkdir()
    (shim / "x.json").write_text("{}", encoding="utf-8")

    import mast_freegsnke.pipeline as pipe

    monkeypatch.setattr(pipe, "_is_windows_reparse_point", lambda p: p.name == "contracts")
    monkeypatch.setattr(pipe, "_remove_layout_shim", lambda p: __import__("shutil").rmtree(p, ignore_errors=True))

    n = _sanitize_history_reparse_points(run)
    assert n >= 1
    assert not shim.exists()


def test_archive_skips_layout_shim_names(tmp_path: Path, monkeypatch) -> None:
    run = tmp_path / "30201"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
    (run / "06_authorities").mkdir()
    (run / "06_authorities" / "contracts").mkdir()
    (run / "06_authorities" / "contracts" / "coil.json").write_text("{}", encoding="utf-8")
    # Fake a shim directory name that looks like a reparse point via monkeypatch
    shim = run / "contracts"
    shim.mkdir()
    (shim / "MOVED.txt").write_text("moved\n", encoding="utf-8")

    # Treat shim as reparse point
    import mast_freegsnke.pipeline as pipe

    real = pipe._is_windows_reparse_point

    def fake_reparse(path: Path) -> bool:
        # Only the top-level layout shim — not nested 06_authorities/contracts.
        if path.name == "contracts" and path.parent == run:
            return True
        return real(path)

    monkeypatch.setattr(pipe, "_is_windows_reparse_point", fake_reparse)

    # contracts has MOVED.txt so rmdir may fail — use unlink via remove that deletes tree stub
    def remove_shim(p: Path) -> None:
        import shutil

        shutil.rmtree(p, ignore_errors=True)

    monkeypatch.setattr(pipe, "_remove_layout_shim", remove_shim)

    dest = _archive_prior_run(run)
    assert dest is not None
    hist = run / dest
    assert (hist / "06_authorities" / "contracts" / "coil.json").is_file()
    assert not (hist / "contracts").exists()
    assert list(run.iterdir()) == [run / "history"] or (run / "history").exists()
