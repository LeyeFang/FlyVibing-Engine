"""Test node map guard — every test is registered and the generated view is fresh.

TIER: core

Usage:
    .venv-py314t\\Scripts\\python.exe Test/Application/Core/test_test_map.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
while ROOT and not (ROOT / "startup.bat").exists():
    parent = ROOT.parent
    if parent == ROOT:
        ROOT = None
        break
    ROOT = parent
assert ROOT is not None, "repo root not found (startup.bat)"

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "Utils/Dev/test_map.py", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    print("-- test node map --")
    result = _run("check")
    check("map check", result.returncode == 0, (result.stdout + result.stderr).strip())

    rendered = _run("render", "--check")
    check(
        "generated markdown is fresh",
        rendered.returncode == 0,
        (rendered.stdout + rendered.stderr).strip(),
    )

    affected = _run("affected", "Application/Core/Scene/SceneManager.py")
    check(
        "SceneManager has related tests",
        affected.returncode == 0 and "scene" in affected.stdout.lower(),
        (affected.stdout + affected.stderr).strip(),
    )

    print()
    if _failures:
        print(f"RESULT: FAIL ({len(_failures)}): {', '.join(_failures)}")
        return 1
    print(f"RESULT: OK ({2 + 1})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
