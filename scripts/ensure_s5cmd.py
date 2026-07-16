#!/usr/bin/env python3
"""Ensure tools/s5cmd.exe exists (Windows/Linux) for FAIR-MAST downloads."""
from __future__ import annotations

import io
import platform
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def main() -> int:
    system = platform.system().lower()
    machine = platform.machine().lower()
    TOOLS.mkdir(exist_ok=True)
    if system == "windows":
        url = "https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Windows-64bit.zip"
        target = TOOLS / "s5cmd.exe"
    elif system == "linux":
        url = "https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-64bit.tar.gz"
        target = TOOLS / "s5cmd"
    else:
        print(f"[FAIL] unsupported platform {system}/{machine}")
        return 2
    if target.exists():
        print(f"[OK] already present: {target}")
        return 0
    print(f"[INFO] downloading {url}")
    data = urllib.request.urlopen(url, timeout=120).read()
    if url.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(data))
        for n in z.namelist():
            if n.lower().endswith("s5cmd.exe") or n.endswith("/s5cmd") or n == "s5cmd":
                target.write_bytes(z.read(n))
                break
        else:
            raise RuntimeError(f"s5cmd binary not found in archive: {z.namelist()[:20]}")
    else:
        import tarfile

        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
        member = next(m for m in tar.getmembers() if m.name.endswith("s5cmd") and m.isfile())
        target.write_bytes(tar.extractfile(member).read())
        target.chmod(0o755)
    print(f"[OK] wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
