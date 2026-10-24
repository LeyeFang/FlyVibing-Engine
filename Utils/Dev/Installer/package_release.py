"""Assemble a release folder from the compiled Windows installer.

The installer itself stays the primary download.  This script adds the small
files that make a release auditable without hiding the ``.exe`` inside a zip:

    FlyVibingEngine-<version>-Windows-x64/
        FlyVibingEngine-Setup-<version>.exe
        CHECKSUMS.sha256
        CHANGELOG.md
        LICENSE
        README-INSTALL.txt

Usage:
    .venv-py314t\\Scripts\\python.exe Utils/Dev/Installer/package_release.py
    # optional: also create a zip of the folder
    .venv-py314t\\Scripts\\python.exe Utils/Dev/Installer/package_release.py --zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
DIST = HERE / "dist"
STAGE = HERE / "build" / "stage"


def _version() -> str:
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"missing release input: {source}")
    shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None,
                        help="engine version (default: pyproject.toml)")
    parser.add_argument("--zip", action="store_true",
                        help="also create a zip of the release folder")
    parser.add_argument("--no-clean", action="store_true",
                        help="keep an existing release folder")
    args = parser.parse_args()

    version = str(args.version or _version())
    installer = DIST / f"FlyVibingEngine-Setup-{version}.exe"
    if not installer.is_file():
        raise SystemExit(
            f"installer not found: {installer}\n"
            "  build it first: python Utils/Dev/Installer/build_installer.py"
        )

    out = DIST / f"FlyVibingEngine-{version}-Windows-x64"
    if out.is_dir() and not args.no_clean:
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    _copy(installer, out / installer.name)
    for source, name in (
        (ROOT / "CHANGELOG.md", "CHANGELOG.md"),
        (ROOT / "LICENSE", "LICENSE"),
        (STAGE / "README-INSTALL.txt", "README-INSTALL.txt"),
    ):
        _copy(source, out / name)

    # Checksums cover everything except the checksum file itself.
    files = sorted(p for p in out.iterdir() if p.is_file())
    lines = [f"{_sha256(p)}  {p.name}" for p in files]
    (out / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="ascii")

    manifest = {
        "product": "FlyVibingEngine",
        "version": version,
        "platform": "windows-x64",
        "built": date.today().isoformat(),
        "installer": installer.name,
        "sha256": _sha256(installer),
        "files": [p.name for p in files] + ["CHECKSUMS.sha256"],
    }
    (out / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[release] {out}")
    for path in sorted(out.iterdir()):
        print(f"  {path.name:40} {path.stat().st_size:>12,} bytes")

    if args.zip:
        zip_path = DIST / f"FlyVibingEngine-{version}-Windows-x64.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(out.iterdir()):
                if path.is_file():
                    zf.write(path, arcname=f"{out.name}/{path.name}")
        print(f"[release] zip: {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
