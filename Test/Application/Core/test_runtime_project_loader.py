"""
RuntimeProjectLoader — 无头测试。

覆盖:
  1. 真实工程 MI-SSSEP 加载: id_map / material 注册名 / warnings
     （id_map 依赖内置材质数量 — 内置材质变动时此处 +1 同步）
  2. 场景加载: node_graph 水合（NodeCanvas 契约）+ material 重映射
  3. remap_scene_materials 直接单测（旧 id 4 → 新 id 3）
  4. GraphEvaluator 构造冒烟（播放器链路前置）
  5. 边界守卫: Application/Core/Project/** 不得 import Editor / imgui_bundle

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Core/test_runtime_project_loader.py
"""

from __future__ import annotations

import os
import re
import sys

# ── 路径引导（与 test_pie_bare.py 同模式）──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)  # 仓库根
PROJECT_PATH = os.path.join(ROOT, "Test", "TestProject", "MI-SSSEP", "MI-SSSEP.myproj")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("RuntimeProjectLoader — Tests")
    print("=" * 60)

    # ── 前置: ResourceManager 初始化（内置资源加载, 基准 material_count）──
    from Application.Core.Engine import Engine
    from Application.Resource.ResourceManager import ResourceManager

    ResourceManager.Init(Engine)

    # ── 1. 工程加载 ──
    print("── Project load ──")
    from Application.Core.Project import (
        load_project,
        load_resources,
        load_scene,
        remap_scene_materials,
    )

    proj = load_project(PROJECT_PATH)
    check("project name", proj.name == "MI-SSSEP", proj.name)
    check("startup scene = MI.scene", proj.startup_scene.endswith("MI.scene"), proj.startup_scene)
    check("4 scenes listed", len(proj.scene_list) == 4, str(proj.scene_list))

    id_map = load_resources(proj)
    # 注: 记录已与活 id 对齐 (2026-10-16 MI-SSSEP 数据修复后) → id_map 为恒等映射。
    #     内置材质 Default=1 + DefaultLit=2 → 工程材质从 3 起编 (新增内置材质时此表 +1)
    check("id_map {3:3, 4:4}", id_map == {3: 3, 4: 4}, str(id_map))
    check("material #3 = 'cue'", ResourceManager.loaded_material.get("3") is not None
          and ResourceManager.loaded_material["3"].name == "cue")
    check("material #4 = 'task'", ResourceManager.loaded_material.get("4") is not None
          and ResourceManager.loaded_material["4"].name == "task")
    check("no warnings", proj.warnings == [], str(proj.warnings))

    # ── 2. 场景加载 + node_graph 水合 ──
    print("── Scene load ──")
    from Application.Core.NodeGraph.canvas import NodeCanvas

    scene = load_scene(proj, proj.startup_scene)
    check("scene name = MI", scene.name == "MI", scene.name)
    check("scene has entities", len(scene.entities) > 0, str(len(scene.entities)))
    check("node_graph hydrated to NodeCanvas",
          isinstance(scene.node_graph, NodeCanvas),
          type(scene.node_graph).__name__)
    check("scene._file_path tracked", getattr(scene, "_file_path", "") != "")

    # ── 3. remap 直接单测: 旧 id 4 → 3 ──
    print("── Material remap ──")
    target_ed = None
    for _eid, ed in scene.entities.items():
        if ed.components.get("MeshRenderer") is not None:
            target_ed = ed
            break
    if target_ed is None:
        check("entity with MeshRenderer found", False)
    else:
        mr = target_ed.components["MeshRenderer"]
        if isinstance(mr, dict):
            mr["material_id"] = 4
            n = remap_scene_materials(scene, {4: 3})
            check("dict MeshRenderer 4 → 3", mr["material_id"] == 3 and n >= 1,
                  f"got {mr.get('material_id')}, n={n}")
        else:
            mr.material_id = 4
            n = remap_scene_materials(scene, {4: 3})
            check("object MeshRenderer 4 → 3", mr.material_id == 3 and n >= 1,
                  f"got {mr.material_id}, n={n}")

    # ── 4. 全部场景可加载（节点图可选）+ GraphEvaluator 冒烟 ──
    #     注意: 非启动场景允许没有 node_graph（如 SSSEP 纯视觉场景）
    print("── All scenes + evaluator smoke ──")
    from Application.Core.NodeGraph import _TYPES
    from Application.Core.NodeGraph.evaluator_engine import GraphEvaluator

    with_graph: list[str] = []
    for rel in proj.scene_list:
        try:
            s = load_scene(proj, rel)
            if isinstance(s.node_graph, NodeCanvas):
                with_graph.append(rel)
            check(f"scene '{os.path.basename(rel)}' loads ({len(s.entities)} entities)",
                  len(s.entities) > 0)
        except Exception as e:  # noqa: BLE001
            check(f"scene '{os.path.basename(rel)}' loads", False, repr(e))
    print(f"  [info] scenes with node_graph: {[os.path.basename(r) for r in with_graph]}")
    check("startup scene carries node_graph", proj.startup_scene in with_graph,
          str(with_graph))

    try:
        evaluator = GraphEvaluator(scene.node_graph, _TYPES)
        check("GraphEvaluator constructs", evaluator is not None)
    except Exception as e:  # noqa: BLE001
        check("GraphEvaluator constructs", False, repr(e))

    # ── 5. 边界: Core/Project 不得依赖 Editor / imgui ──
    print("── Boundary scan (Core/Project) ──")
    forbidden = re.compile(r"^\s*(from|import)\s+(Application\.Editor|imgui_bundle)\b")
    hits: list[str] = []
    proj_core = os.path.join(ROOT, "Application", "Core", "Project")
    for fname in sorted(os.listdir(proj_core)):
        if not fname.endswith(".py"):
            continue
        with open(os.path.join(proj_core, fname), "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if forbidden.match(line):
                    hits.append(f"{fname}:{lineno}: {line.strip()}")
    check("no Editor/imgui imports", not hits, "; ".join(hits))

    # ── Summary ──
    print()
    print("=" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    if _RESULTS["fail"] == 0:
        print("ALL TESTS PASSED")
        return 0
    print("TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
