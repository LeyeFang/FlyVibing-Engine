"""Game export extension scope — on-demand node-pack selection.

Locks the split between the two distribution policies:

* game export: user-specific, on-demand. Only extension directories whose
  node packs are referenced by the project's scenes are copied; `export:false`
  remains a hard opt-out.
* installer: mainline allowlist (`Application/Functions/official_extensions.json`),
  tested separately in `test_release_layout.py`.

TIER: core
"""

from __future__ import annotations

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


def main() -> int:
    print("=" * 60)
    print("Game export extension scope — on-demand")
    print("=" * 60)

    from Application.Core.NodeGraph.node_packs import NodePackRegistry
    from Application.Editor.ProjectManager import ProjectManager

    funcs = os.path.join(ROOT, "Application", "Functions")
    device_dir = os.path.abspath(os.path.join(funcs, "SerialParallelDevice"))
    bci_dir = os.path.abspath(os.path.join(funcs, "BCIAlgorithm"))
    virtual_dir = os.path.abspath(os.path.join(funcs, "VirtualDevice"))

    # ── 1. 类型 → 扩展目录映射 ──
    dirs, unresolved = NodePackRegistry.extension_dirs_for_types(
        {"SerialSend", "OnGameStart", "ExtTypeThatDoesNotExist"})
    check("SerialSend maps to SerialParallelDevice", device_dir in dirs, str(dirs))
    check("unrelated extensions are not required", bci_dir not in dirs and virtual_dir not in dirs,
          str(dirs))
    check("unknown node type is reported", unresolved == {"ExtTypeThatDoesNotExist"},
          str(unresolved))

    # ── 2. scene node_type 收集 ──
    with tempfile.TemporaryDirectory(prefix="mge_export_scope_") as tmp:
        scene = os.path.join(tmp, "scenes", "Main.scene")
        os.makedirs(os.path.dirname(scene))
        with open(scene, "w", encoding="utf-8") as fh:
            json.dump({
                "version": "0.1.0",
                "scene": {
                    "node_graph": {
                        "nodes": {
                            "1": {"node_type": "OnGameStart"},
                            "2": {"node_type": "SerialSend"},
                            "3": {"type": "ParallelSend"},
                        }
                    }
                }
            }, fh)
        types = ProjectManager._scene_node_types(tmp, ["scenes/Main.scene"])
        check("scene node types collected", types == {"OnGameStart", "SerialSend", "ParallelSend"},
              str(types))

        bare = os.path.join(tmp, "scenes", "Bare.scene")
        with open(bare, "w", encoding="utf-8") as fh:
            json.dump({"node_graph": {"nodes": [{"node_type": "SerialSend"}]}}, fh)
        bare_types = ProjectManager._scene_node_types(tmp, ["scenes/Bare.scene"])
        check("bare scene JSON also parsed", bare_types == {"SerialSend"}, str(bare_types))

        required, warnings, details = ProjectManager._resolve_export_extensions(ROOT, types)
        check("required extension directory selected", required == {device_dir}, str(required))
        check("on-demand mode recorded", details.get("mode") == "on_demand", str(details))
        check("known node types produce no warning", not warnings, str(warnings))

        excluded = ProjectManager._export_excluded_paths(ROOT, required)
        check("used extension is not excluded from game", device_dir not in excluded)
        check("unused official extension is excluded from game",
              bci_dir in excluded and virtual_dir in excluded, str(sorted(excluded)))
        check("editor local config remains excluded",
              os.path.abspath(os.path.join(ROOT, "Application", "Editor", "Config"))
              in ProjectManager._local_state_paths(ROOT))

        # 实际复制过滤（游戏层使用同一 _copy_tree_for_export）
        copied = os.path.join(tmp, "game_functions")
        copy_warnings: list[str] = []
        ProjectManager._copy_tree_for_export(
            funcs, copied, copy_warnings, exclude_paths=excluded)
        check("game copy retains used extension",
              os.path.isdir(os.path.join(copied, "SerialParallelDevice")))
        check("game copy drops unused extensions",
              not os.path.isdir(os.path.join(copied, "BCIAlgorithm"))
              and not os.path.isdir(os.path.join(copied, "VirtualDevice")))

    print()
    print("=" * 60)
    total = _passed + len(_failed)
    print(f"Results: {_passed}/{total} passed, {len(_failed)} failed")
    print("ALL TESTS PASSED" if not _failed else "TESTS FAILED")
    return 0 if not _failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
