"""Single source of truth for release artifact names and locations.

Every platform package (Windows installer, macOS dmg, Linux AppImage/zip)
uses the same layout::

    <installer>/dist/releases/v<version>/<platform>-<arch>/
        <Product>-...-<Platform>-<Arch>.<ext>
        CHECKSUMS.sha256
        CHANGELOG.md
        LICENSE
        README-INSTALL.txt
        release-manifest.json

The raw compiler output stays in ``dist/build/`` as an intermediate; only the
folder under ``dist/releases/`` is intended for upload.
"""

from __future__ import annotations

from pathlib import Path

PRODUCT = "FlyVibingEngine"
PLATFORM = "Windows"
ARCH = "x64"
INSTALLER_DIR = Path(__file__).resolve().parent
DIST_ROOT = INSTALLER_DIR / "dist"
BUILD_DIR = DIST_ROOT / "build"
RELEASE_ROOT = DIST_ROOT / "releases"


def version_tag(version: str) -> str:
    return f"v{str(version).lstrip('v')}"


def platform_slug(platform: str = PLATFORM, arch: str = ARCH) -> str:
    return f"{platform.lower()}-{arch}"


PLATFORM_SLUG = platform_slug()


def installer_name(
    version: str,
    platform: str = PLATFORM,
    arch: str = ARCH,
    extension: str = ".exe",
) -> str:
    """Installer file name, platform and arch explicit."""
    return f"{PRODUCT}-Setup-{str(version).lstrip('v')}-{platform}-{arch}{extension}"


def platform_dir(
    version: str,
    platform: str = PLATFORM,
    arch: str = ARCH,
) -> Path:
    """Canonical upload folder for one version/platform."""
    return RELEASE_ROOT / version_tag(version) / platform_slug(platform, arch)


def generic_asset_name(
    version: str,
    extension: str,
    platform: str = PLATFORM,
    arch: str = ARCH,
) -> str:
    """Portable/bundle naming for non-installer assets."""
    return f"{PRODUCT}-{str(version).lstrip('v')}-{platform}-{arch}{extension}"
