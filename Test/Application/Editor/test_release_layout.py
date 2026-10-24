"""Release artifact naming and location contract.

The installer must always write an explicitly platform-tagged executable and
the uploadable bundle must always live under::

    Utils/Dev/Installer/dist/releases/v<version>/<platform>-<arch>/

Keeping this test cheap makes it safe to run in the core tier.

TIER: core
"""

from __future__ import annotations

import importlib.util
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
INSTALLER_DIR = os.path.join(ROOT, "Utils", "Dev", "Installer")

_passed = 0
_failed: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def _load_layout():
    path = os.path.join(INSTALLER_DIR, "release_layout.py")
    spec = importlib.util.spec_from_file_location("release_layout", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    print("Release layout")
    layout = _load_layout()

    check("product name", layout.PRODUCT == "FlyVibingEngine", layout.PRODUCT)
    check("platform label", layout.PLATFORM == "Windows", layout.PLATFORM)
    check("arch label", layout.ARCH == "x64", layout.ARCH)
    check("platform slug", layout.PLATFORM_SLUG == "windows-x64", layout.PLATFORM_SLUG)

    installer = layout.installer_name("1.0.0")
    check("installer name embeds platform and arch",
          installer == "FlyVibingEngine-Setup-1.0.0-Windows-x64.exe", installer)

    folder = layout.platform_dir("1.0.0")
    expected = layout.RELEASE_ROOT / "v1.0.0" / "windows-x64"
    check("release folder contract", folder == expected, str(folder))
    check("version tag normalization",
          layout.platform_dir("v1.0.0") == expected,
          str(layout.platform_dir("v1.0.0")))

    check("installer name normalizes v prefix",
          layout.installer_name("v1.0.0") == installer, layout.installer_name("v1.0.0"))

    check("portable asset name",
          layout.generic_asset_name("1.0.0", ".zip")
          == "FlyVibingEngine-1.0.0-Windows-x64.zip",
          layout.generic_asset_name("1.0.0", ".zip"))

    mac_folder = layout.platform_dir("1.0.0", "macOS", "arm64")
    check("cross-platform release folder",
          mac_folder == layout.RELEASE_ROOT / "v1.0.0" / "macos-arm64",
          str(mac_folder))
    check("cross-platform installer name",
          layout.installer_name("1.0.0", "macOS", "arm64", ".dmg")
          == "FlyVibingEngine-Setup-1.0.0-macOS-arm64.dmg",
          layout.installer_name("1.0.0", "macOS", "arm64", ".dmg"))

    iss_path = os.path.join(INSTALLER_DIR, "installer.iss")
    with open(iss_path, encoding="utf-8") as fh:
        iss = fh.read()
    check("Inno Setup uses platform tag",
          'PlatformTag "Windows-x64"' in iss
          and "OutputBaseFilename=FlyVibingEngine-Setup-{#AppVersion}-{#PlatformTag}" in iss,
          "installer.iss output name missing platform tag")

    with open(os.path.join(INSTALLER_DIR, "package_release.py"), encoding="utf-8") as fh:
        packager = fh.read()
    check("packager uses canonical folder",
          "out = platform_dir(version)" in packager,
          "package_release.py does not call platform_dir(version)")

    if _failed:
        print(f"\n{_passed} passed, {len(_failed)} failed")
        return 1
    print(f"\n{_passed} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
