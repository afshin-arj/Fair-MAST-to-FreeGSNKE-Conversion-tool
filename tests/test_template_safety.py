from __future__ import annotations

from pathlib import Path
import tempfile

from mast_freegsnke.generate import ScriptGenerator


def test_templates_render_without_format_collisions() -> None:
    repo = Path(__file__).resolve().parents[1]
    templates = repo / "templates"
    gen = ScriptGenerator(templates_dir=templates)

    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td) / "run"
        machine_dir = Path(td) / "machine_authority"
        machine_dir.mkdir(parents=True, exist_ok=True)

        gen.generate(run_dir=run_dir, machine_dir=machine_dir, formed_frac=0.8)

        inv = (run_dir / "inverse_run.py").read_text(encoding="utf-8")
        fwd = (run_dir / "forward_run.py").read_text(encoding="utf-8")

        assert "machine_authority" in inv
        assert "0.8" in inv
        assert "machine_authority" in fwd
        # ensure no template tokens remain
        assert "__MACHINE_DIR_REPR__" not in inv
        assert "__FORMED_FRAC__" not in inv
        assert "__MACHINE_DIR_REPR__" not in fwd
