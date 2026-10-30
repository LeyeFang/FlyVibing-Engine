"""Release artifact naming and location contract.

The installer must always write an explicitly platform-tagged executable and
the uploadable bundle must always live under::

    Utils/Dev/Installer/dist/releases/v<version>/<platform>-<arch>/

Keeping this test cheap makes it safe to run in the core tier.

TIER: core
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

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


def _load_build_installer():
    path = os.path.join(INSTALLER_DIR, "build_installer.py")
    if INSTALLER_DIR not in sys.path:
        sys.path.insert(0, INSTALLER_DIR)
    spec = importlib.util.spec_from_file_location("build_installer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_installer_allowlist(builder) -> None:
    """Installer staging must use the mainline allowlist, not game export attributes."""
    with tempfile.TemporaryDirectory() as tmp:
        funcs = os.path.join(tmp, "Functions")
        local = os.path.join(funcs, "LocalFixture")
        official = os.path.join(funcs, "OfficialKeep")
        os.makedirs(local)
        os.makedirs(official)
        # 本地 fixture 未开 export:false —— 安装包仍必须排除（allowlist 才是版权边界）
        with open(os.path.join(local, "extension.json"), "w", encoding="utf-8") as fh:
            json.dump({"id": "local", "export": True}, fh)
        # 官方扩展对 game 关闭，但仍是主线安装包的一部分（不得错杀）
        with open(os.path.join(official, "extension.json"), "w", encoding="utf-8") as fh:
            json.dump({"id": "official", "export": False}, fh)
        with open(os.path.join(funcs, "official_extensions.json"), "w", encoding="utf-8") as fh:
            json.dump({"extensions": [{"id": "official", "dir": "OfficialKeep"}]}, fh)

        blocked = builder._nonofficial_extension_dirs(funcs)
        check("local fixture excluded by installer allowlist",
              os.path.normcase(os.path.abspath(local)) in
              {os.path.normcase(p) for p in blocked}, str(blocked))
        check("official export:false extension kept in installer",
              os.path.normcase(os.path.abspath(official)) not in
              {os.path.normcase(p) for p in blocked}, str(blocked))
        out = os.path.join(tmp, "stage", "Functions")
        builder._copy_tree(funcs, out, exclude_paths=blocked)
        check("installer staging has no local fixture",
              not os.path.exists(os.path.join(out, "LocalFixture")),
              "local fixture leaked into installer staging")
        check("installer staging retains official export:false extension",
              os.path.exists(os.path.join(out, "OfficialKeep")),
              "official extension was incorrectly filtered by export:false")


def _check_local_state_filter(builder) -> None:
    """Installer staging must not ship git-ignored Application/Editor/Config state."""
    check("local state contract includes editor Config",
          "Application/Editor/Config" in getattr(builder, "_LOCAL_STATE_DIRS", ()),
          str(getattr(builder, "_LOCAL_STATE_DIRS", None)))
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "Application")
        config = os.path.join(src, "Editor", "Config")
        other = os.path.join(src, "Editor", "Other")
        os.makedirs(config)
        os.makedirs(other)
        with open(os.path.join(config, "extensions.json"), "w", encoding="utf-8") as fh:
            json.dump({"enabled": {"local_fixture": True}}, fh)
        with open(os.path.join(other, "keep.py"), "w", encoding="utf-8") as fh:
            fh.write("KEEP = True\n")
        out = os.path.join(tmp, "stage", "Application")
        blocked = {os.path.abspath(os.path.join(tmp, *rel.split("/")))
                   for rel in builder._LOCAL_STATE_DIRS}
        builder._copy_tree(src, out, exclude_paths=blocked)
        check("editor Config excluded from staging",
              not os.path.exists(os.path.join(out, "Editor", "Config")),
              "local editor state leaked into staging")
        check("ordinary Application subtree retained",
              os.path.isfile(os.path.join(out, "Editor", "Other", "keep.py")),
              "normal Application files were removed")


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

    check("installer PATH is written with the install-mode subkey",
          'Root: HKA; Subkey: "Environment"' not in iss
          and "procedure AddToPathIfNeeded" in iss
          and "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment" in iss,
          "PATH must not target HKLM\\Environment directly")
    check("installer removes legacy extension state on upgrade",
          "[InstallDelete]" in iss
          and "Application\\Editor\\Config\\extensions.json" in iss,
          "legacy local extension state may survive an upgrade")

    builder = _load_build_installer()
    _check_installer_allowlist(builder)
    _check_local_state_filter(builder)

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
