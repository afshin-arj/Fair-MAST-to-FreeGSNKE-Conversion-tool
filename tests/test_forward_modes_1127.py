"""v11.27.0 — Forward window currents mode + GIF-expectation / trajectory audit."""

from __future__ import annotations

import json
from pathlib import Path

from mast_freegsnke.execution_authority import (
    default_execution_authority_bundle,
    load_execution_authority_bundle,
    write_execution_authority,
)
from mast_freegsnke.science_audit import (
    forward_gate_summary,
    presentation_advisories,
    profile_trajectory_audit,
)
from mast_freegsnke.shot_suitability import ShotSuitability, assess_shot_suitability

REPO = Path(__file__).resolve().parents[1]


def test_forward_window_currents_default() -> None:
    b = default_execution_authority_bundle()
    assert b.solver.forward_window_currents == "measured_pf"
    assert b.authority_version == "11.32.0"


def test_forward_window_currents_load_roundtrip(tmp_path: Path) -> None:
    root = write_execution_authority(tmp_path)
    path = root / "execution_authority_bundle.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["solver"]["forward_window_currents"] = "inverse_dump_currents"
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    loaded = load_execution_authority_bundle(path)
    assert loaded.solver.forward_window_currents == "inverse_dump_currents"


def test_forward_template_window_currents_tokens() -> None:
    tpl = (REPO / "templates" / "forward_run.py.tpl").read_text(encoding="utf-8")
    assert "forward_window_currents" in tpl
    assert "_forward_window_currents" in tpl
    assert "_window_pf_currents" in tpl
    assert "inverse_dump_currents" in tpl
    assert "SHAPE DEMO" in tpl
    assert "window_currents" in tpl


def test_forward_gate_surfaces_window_currents(tmp_path: Path) -> None:
    run = tmp_path / "SHOT" / "1"
    pres = run / "presentation"
    pres.mkdir(parents=True)
    (pres / "forward_times.json").write_text(
        json.dumps(
            {
                "n_ok": 2,
                "n_converged": 2,
                "n_completed_max_iter": 0,
                "n_skipped": 0,
                "n_times": 2,
                "window_currents": "inverse_dump_currents",
                "ic_psi_used": "inverse_dump",
                "profile_source_requested": "profile_trajectory_if_ok",
                "profile_sources_used": ["profile_trajectory"],
                "per_time": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate = forward_gate_summary(run)
    assert gate["available"] is True
    assert gate["window_currents"] == "inverse_dump_currents"
    adv = presentation_advisories(run)
    blob = " ".join(adv["items"])
    assert "SHAPE DEMO" in blob or "inverse_dump_currents" in blob


def test_profile_trajectory_audit_archive_profiles(tmp_path: Path) -> None:
    run = tmp_path / "r"
    auth = run / "inputs" / "profile_trajectory_authority"
    auth.mkdir(parents=True)
    (auth / "profile_trajectory.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "fit_mode_used": "archive_profiles",
                "knots": [
                    {
                        "t_s": 0.2,
                        "paxis_Pa": 1e4,
                        "fvac": 0.5,
                        "alpha_m": 1.2,
                        "alpha_n": 1.5,
                        "residual": {
                            "alphas_source": "efit_pprime_fit",
                            "pprime_rms_norm": 0.01,
                        },
                    }
                ],
                "provenance": {
                    "fit_mode_used": "archive_profiles",
                    "pprime_var": "pprime",
                    "ffprime_var": "ffprime",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    aud = profile_trajectory_audit(run)
    assert aud["available"] is True
    assert aud["alphas_from_pprime"] is True
    assert aud["fit_mode_used"] == "archive_profiles"


def test_suitability_advisories_on_suitable(tmp_path: Path, monkeypatch) -> None:
    from mast_freegsnke import shot_suitability as ss
    from tests.test_shot_suitability import _cfg

    cfg = _cfg(tmp_path)

    monkeypatch.setattr(ss, "group_cache_hit", lambda cache, g: True)
    monkeypatch.setattr(ss, "cache_dir_for_shot", lambda c, s: tmp_path / f"shot_{s}")
    rep = assess_shot_suitability(cfg, 30201)
    assert rep.suitable is True
    assert rep.advisories
    assert any("measured-PF" in a or "archive EFIT" in a for a in rep.advisories)
    d = rep.to_dict()
    assert "advisories" in d


def test_profile_trajectory_policy_version() -> None:
    pol = json.loads(
        (REPO / "configs" / "profile_trajectory_authority.json").read_text(encoding="utf-8")
    )
    assert pol["authority_version"] == "1.1.0"
    assert "archive_profiles" in pol["notes"]
