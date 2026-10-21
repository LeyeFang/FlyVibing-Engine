"""UI map guard — state/control references and test/scenario links.

TIER: core

Run:
    python Utils/Dev/test_runner.py --only test_ui_map
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
assert ROOT is not None

_FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _FAILURES.append(name)


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
    print("-- ui map --")
    result = _run("ui", "check")
    check("ui check", result.returncode == 0, (result.stdout + result.stderr).strip())

    tree = _run("ui", "tree")
    check("ui tree renders", tree.returncode == 0 and "editor.shell" in tree.stdout,
          (tree.stdout + tree.stderr).strip())

    affected = _run("ui", "affected", "Application/Editor/UI/panels/ScenePanel.py")
    check("ScenePanel controls are indexed",
          affected.returncode == 0 and "editor.panel.scene" in affected.stdout,
          (affected.stdout + affected.stderr).strip())

    tests = _run("ui", "tests", "editor.panel.scene")
    check("controls expose test nodes",
          tests.returncode == 0 and "editor.scene_panel_interactions" in tests.stdout,
          (tests.stdout + tests.stderr).strip())

    coverage = _run("ui", "coverage")
    check("all public ops have a UI/agent-only mapping",
          coverage.returncode == 0 and "missing: -" in coverage.stdout,
          (coverage.stdout + coverage.stderr).strip())

    find = _run("ui", "show", "editor.node_editor.find_window")
    groups = _run("ui", "show", "editor.node_editor.groups_window")
    check("Find/Groups windows are indexed",
          find.returncode == 0 and groups.returncode == 0
          and "node_editor_find" in find.stdout
          and "node_groups_smoke" in groups.stdout,
          (find.stdout + find.stderr + groups.stdout + groups.stderr).strip())

    print()
    if _FAILURES:
        print(f"RESULT: FAIL ({len(_FAILURES)}): {', '.join(_FAILURES)}")
        return 1
    print("RESULT: OK (6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
