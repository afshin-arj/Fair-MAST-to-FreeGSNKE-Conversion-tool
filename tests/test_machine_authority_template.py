from __future__ import annotations

from pathlib import Path

from mast_freegsnke.machine_authority import (
    MachineAuthority,
    machine_authority_from_dir,
    validate_machine_authority,
)


def test_template_authority_rejected(tmp_path: Path) -> None:
    ma = MachineAuthority(
        root=tmp_path,
        manifest={
            "schema_version": "1.0",
            "authority_name": "X",
            "authority_version": "0.0-template",
            "provenance": {"source_repo": "CHANGE_ME"},
        },
        probe_geometry={
            "schema_version": "1.0",
            "notes": "TEMPLATE",
            "flux_loops": [],
            "pickup_coils": [],
        },
        coil_geometry={"schema_version": "1.0", "coils": []},
        diagnostic_registry={"schema_version": "1.0", "diagnostics": []},
    )
    rep = validate_machine_authority(ma)
    assert not rep["ok"]
    assert any("template" in e for e in rep["errors"])


def test_shipped_machine_authority_is_fairmast() -> None:
    root = Path(__file__).resolve().parents[1] / "machine_authority"
    ma, rep = machine_authority_from_dir(root)
    assert rep.get("ok") is True
    assert ma is not None
    assert "fairmast" in str(ma.manifest.get("authority_version", "")).lower()
    assert len(ma.probe_geometry.get("flux_loops", [])) > 0
    assert len(ma.probe_geometry.get("pickup_coils", [])) > 0
