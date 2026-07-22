from __future__ import annotations

from pathlib import Path

from mast_freegsnke.freegsnke_runner import FreeGSNKERunner, resolve_freegsnke_python


def test_runner_records_import_error_hint(tmp_path: Path):
    """Deterministic: the script itself raises the import failure, so this test
    does not depend on whether freegsnke happens to be installed in the test
    interpreter."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    script = run_dir / "inverse_run.py"
    script.write_text("raise ModuleNotFoundError(\"No module named 'freegsnke'\")\n")

    r = FreeGSNKERunner().run_script(script, run_dir=run_dir, label="inverse")
    assert r.ok is False
    assert r.returncode != 0
    stderr = (run_dir / r.stderr_path).read_text()
    assert "freegsnke" in stderr
    assert r.error_hint in {"freegsnke_not_installed_in_selected_python", "freegsnke_import_error"}


def test_runner_success_records_logs(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    script = run_dir / "forward_run.py"
    script.write_text("print('ok')\n")

    r = FreeGSNKERunner().run_script(script, run_dir=run_dir, label="forward")
    assert r.ok is True
    assert r.returncode == 0
    assert (run_dir / r.stdout_path).read_text().strip() == "ok"
    assert r.error_hint is None


def test_runner_prepends_repo_src_for_mast_freegsnke_import(tmp_path: Path):
    """FreeGSNKE venv often lacks pip-installed mast_freegsnke; PYTHONPATH must expose src/."""
    from mast_freegsnke.freegsnke_runner import resolve_repo_src

    src = resolve_repo_src()
    assert src is not None
    assert (src / "mast_freegsnke" / "equilibrium_presentation.py").is_file()

    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    script = run_dir / "check_import.py"
    script.write_text(
        "from mast_freegsnke.equilibrium_presentation import PresentationAuthority\n"
        "print(PresentationAuthority().write_equilibrium_gifs)\n"
    )
    r = FreeGSNKERunner(repo_root=src.parent).run_script(script, run_dir=run_dir, label="check")
    assert r.ok is True, (run_dir / r.stderr_path).read_text()
    assert (run_dir / r.stdout_path).read_text().strip() == "True"


def test_resolve_freegsnke_python_falls_back_across_venv_layouts(tmp_path: Path):
    venv = tmp_path / ".venv-freegsnke"
    posix = venv / "bin" / "python"
    posix.parent.mkdir(parents=True)
    posix.write_text("", encoding="utf-8")
    # Configured Windows path missing → should resolve to POSIX sibling.
    resolved = resolve_freegsnke_python(
        str(venv / "Scripts" / "python.exe"),
        repo_root=tmp_path,
    )
    assert Path(resolved) == posix.resolve()
