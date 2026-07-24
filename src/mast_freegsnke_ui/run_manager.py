"""Subprocess runner for ``mast-freegsnke run`` (one shot at a time)."""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Deque, Dict, List, Optional


class RunManager:
    """Launch and monitor a single pipeline subprocess."""

    def __init__(self, *, log_maxlen: int = 400) -> None:
        self._proc: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()
        self._log: Deque[str] = collections.deque(maxlen=log_maxlen)
        self._shot: Optional[int] = None
        self._returncode: Optional[int] = None
        self._started_at: Optional[float] = None
        self._reader: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def shot(self) -> Optional[int]:
        return self._shot

    def start(
        self,
        shot: int,
        *,
        config: Path,
        cwd: Path,
        python_exe: Optional[Path] = None,
    ) -> None:
        if self.is_running:
            raise RuntimeError("A run is already in progress")
        shot = int(shot)
        config = Path(config)
        cwd = Path(cwd)
        py = str(python_exe or sys.executable)
        cmd = [
            py,
            "-m",
            "mast_freegsnke.cli",
            "run",
            "--shot",
            str(shot),
            "--config",
            str(config),
        ]
        with self._lock:
            self._log.clear()
            self._shot = shot
            self._returncode = None
            self._started_at = time.time()
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ},
            )
            proc = self._proc
        self._reader = threading.Thread(target=self._pump, args=(proc,), daemon=True)
        self._reader.start()

    def _pump(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                with self._lock:
                    self._log.append(line.rstrip("\n"))
        except Exception as e:  # noqa: BLE001 — surface in log tail
            with self._lock:
                self._log.append(f"[ui] log reader error: {e}")
        finally:
            rc = proc.wait()
            with self._lock:
                self._returncode = rc
                self._log.append(f"[ui] process exited rc={rc}")

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        pid = proc.pid
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        with self._lock:
            self._log.append("[ui] cancelled by user")
            if self._returncode is None:
                self._returncode = -1

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            lines = list(self._log)
            return {
                "running": running,
                "shot": self._shot,
                "returncode": self._returncode,
                "log_lines": lines[-50:],
                "started_at": self._started_at,
            }

    def log_text(self) -> str:
        return "\n".join(self.snapshot()["log_lines"])  # type: ignore[arg-type]
