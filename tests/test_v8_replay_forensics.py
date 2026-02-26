from __future__ import annotations

from pathlib import Path
import json

from mast_freegsnke.util import write_json, sha256_file
from mast_freegsnke.replay.replayer import replay_run
from mast_freegsnke.forensics.compare import forensic_compare


def test_v8_replay_and_forensic(tmp_path: Path):
    # Create two minimal "pack" dirs with pack_manifest.json
    A = tmp_path / "A"
    B = tmp_path / "B"
    A.mkdir()
    B.mkdir()

    (A / "x.txt").write_text("hello", encoding="utf-8")
    (B / "x.txt").write_text("hello", encoding="utf-8")
    (B / "y.txt").write_text("extra", encoding="utf-8")

    manA = {"schema_version":"v8.0.0", "files":[{"path":"x.txt","sha256":sha256_file(A/"x.txt")}]}
    manB = {"schema_version":"v8.0.0", "files":[{"path":"x.txt","sha256":sha256_file(B/"x.txt")},
                                                {"path":"y.txt","sha256":sha256_file(B/"y.txt")}]}
    write_json(A/"pack_manifest.json", manA)
    write_json(B/"pack_manifest.json", manB)

    repA = replay_run(A, mode="relaxed")
    assert repA.ok

    delta = forensic_compare(A, B, out_dir=tmp_path/"out")
    assert not delta.ok
    assert delta.n_only_B == 1
    assert (tmp_path/"out"/"FORENSIC_DELTA.json").exists()
