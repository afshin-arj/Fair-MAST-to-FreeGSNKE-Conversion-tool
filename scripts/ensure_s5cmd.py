#!/usr/bin/env python3
"""Ensure tools/s5cmd(.exe) exists for FAIR-MAST Level-2 downloads.

Supports Windows / Linux / macOS for amd64 and arm64 release archives.
"""
from __future__ import annotations

import io
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
VERSION = "2.3.0"
BASE = f"https://github.com/peak/s5cmd/releases/download/v{VERSION}"


def _release_spec() -> tuple[str, Path]:
    """Return (download_url, target_path) for this host."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    is_arm = machine in {"arm64", "aarch64"}
    is_x86_64 = machine in {"x86_64", "amd64", "x64"}

    if system == "windows":
        if is_arm:
            name = f"s5cmd_{VERSION}_Windows-arm64.zip"
        elif is_x86_64 or machine in {"", "i386", "i686"}:
            # Default Windows CI / desktop hosts are amd64; 32-bit gets 64-bit zip name historically.
            name = f"s5cmd_{VERSION}_Windows-64bit.zip"
        else:
            raise RuntimeError(f"unsupported Windows arch: {machine}")
        return f"{BASE}/{name}", TOOLS / "s5cmd.exe"

    if system == "linux":
        if is_arm:
            name = f"s5cmd_{VERSION}_Linux-arm64.tar.gz"
        elif is_x86_64:
            name = f"s5cmd_{VERSION}_Linux-64bit.tar.gz"
        else:
            raise RuntimeError(f"unsupported Linux arch: {machine}")
        return f"{BASE}/{name}", TOOLS / "s5cmd"

    if system == "darwin":
        if is_arm:
            name = f"s5cmd_{VERSION}_macOS-arm64.tar.gz"
        elif is_x86_64:
            name = f"s5cmd_{VERSION}_macOS-64bit.tar.gz"
        else:
            raise RuntimeError(f"unsupported macOS arch: {machine}")
        return f"{BASE}/{name}", TOOLS / "s5cmd"

    raise RuntimeError(f"unsupported platform {system}/{machine}")


def _extract_binary(url: str, data: bytes, target: Path) -> None:
    if url.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(data))
        for n in z.namelist():
            base = Path(n).name.lower()
            if base in {"s5cmd.exe", "s5cmd"}:
                target.write_bytes(z.read(n))
                return
        raise RuntimeError(f"s5cmd binary not found in archive: {z.namelist()[:20]}")

    tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    member = next(
        (m for m in tar.getmembers() if Path(m.name).name == "s5cmd" and m.isfile()),
        None,
    )
    if member is None:
        raise RuntimeError("s5cmd binary not found in tar archive")
    extracted = tar.extractfile(member)
    if extracted is None:
        raise RuntimeError("failed to extract s5cmd from tar archive")
    target.write_bytes(extracted.read())
    target.chmod(0o755)


def main() -> int:
    TOOLS.mkdir(exist_ok=True)
    try:
        url, target = _release_spec()
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        return 2

    if target.exists() and target.stat().st_size > 0:
        print(f"[OK] already present: {target}")
        return 0

    print(f"[INFO] downloading {url}")
    try:
        data = urllib.request.urlopen(url, timeout=120).read()
    except Exception as e:
        print(f"[FAIL] download failed: {e}")
        return 1

    try:
        _extract_binary(url, data, target)
    except Exception as e:
        print(f"[FAIL] extract failed: {e}")
        return 1

    if not target.exists() or target.stat().st_size <= 0:
        print(f"[FAIL] wrote empty or missing binary: {target}")
        return 1

    print(f"[OK] wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
