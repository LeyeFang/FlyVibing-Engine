"""
Action 契约守卫 — ui_protocol §10 映射表 ↔ ops.py ↔ LiveCommandServer 三方一致 + 选中链行为。

锁定内容 (协议: Doc/Dev/ui_protocol.md §10):
  1. 三方 op 集合相等: 文档映射表 / engine_editor_mcp.ops.OPS / LiveCommandServer._register_ops()
  2. 映射表每行: UI 入口 / 联动 / 机制 列非空
  3. 选中链: select_with_gizmo → 数据层+gizmo 状态; select → gizmo 隐藏; clear → 全清
  4. entity.add 自动选中 (含成为子级); entity.delete 级联清理 (删自身 / 删祖先)
  5. 场景切换 → 选中清理; create_scene → 新场景成为活跃

背景 (2026-10-08 修复): `select_with_gizmo` 曾因 EditorHost 未导入 → NameError 被裸 except
吞掉 → MCP selection.set 长期无 gizmo (静默); 本测试连同契约表一起防止回归。

运行: python Utils/Dev/test_runner.py --only action_contract
"""
# TIER: core

from __future__ import annotations

import os
import re
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)  # repo root
    _SRC = os.path.join(_d, "Utils", "ExtDev", "EditorMcp", "src")
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
_ROOT = _d

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _parse_contract_table(path: str) -> list[tuple[list[str], list[str]]]:
    """解析 ui_protocol §10 映射表 → [(op 名列表, 单元格列表), ...] (跳过表头/图例)。

    边界: 遇下一个一级章节 (## 非 10.) 即停 — §13 等后续章节含同名表格行, 不得误入。
    """
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## 10."))
    rows: list[tuple[list[str], list[str]]] = []
    for ln in lines[start:]:
        if ln.startswith("## ") and not ln.startswith("## 10."):
            break  # §10 结束
        if not ln.startswith("| "):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        names = re.findall(r"`([a-z_]+\.[a-z_0-9.]+)`", cells[0])
        if names:
            rows.append((names, cells))
    return rows


def main() -> int:
    print("=" * 60)
    print("Action contract — ui_protocol §10 × ops.py × LiveCommandServer (headless)")
    print("=" * 60)

    # ═══════════════════════════════════════════════════════════
    # 1. 三方一致性
    # ═══════════════════════════════════════════════════════════
    print("── 1. 3-way registry equality ──")
    # 内容已 CLI 化（2026-10-16）: §10 正文在工具仓 docs_content（引擎侧 md 为指针 stub）
    doc_path = os.path.join(
        _ROOT, "Utils", "ExtDev", "EditorMcp", "src", "engine_editor_mcp",
        "docs_content", "dev", "ui_protocol.md",
    )
    rows = _parse_contract_table(doc_path)
    doc_ops: list[str] = []
    for names, cells in rows:
        doc_ops.extend(names)
        check(f"契约行 {names[0]} 列完整 (入口/联动/机制)",
              len(cells) >= 4 and bool(cells[1]) and bool(cells[2]) and bool(cells[3]),
              str(cells))

    from engine_editor_mcp import ops as mcp_ops
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer

    LiveCommandServer._register_ops()
    registry = set(mcp_ops.OPS)
    live = set(LiveCommandServer._ops)
    doc = set(doc_ops)

    check("op 计数一致 (60 / registry / live / doc)",
          len(registry) == len(live) == len(doc) == 60,
          f"{len(registry)}/{len(live)}/{len(doc)}")
    missing = registry - doc
    extra = doc - registry
    check("文档表 ↔ ops.py 注册表 集合相等",
          not missing and not extra, f"missing={sorted(missing)} extra={sorted(extra)}")
    diff = registry ^ live
    check("ops.py ↔ LiveCommandServer 集合相等",
          not diff, f"sym_diff={sorted(diff)}")

    # ═══════════════════════════════════════════════════════════
    # 2. 选中链行为 (headless 夹具)
    # ═══════════════════════════════════════════════════════════
    print("── 2. selection chain behaviors ──")
    import importlib

    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.Scene import Scene
    from Application.Editor.EditorHost import EditorHost
    from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
    from Application.Editor.UI.controllers.SelectionController import SelectionController
    from Application.Editor.Gizmos.TransformGizmo import TransformGizmo

    _ev = importlib.import_module("Application.Core.Events.Event")
    orig_reg = SceneManager._registry.get("EditorHost")
    orig_scene_attr = EditorHost.scene
    orig_scenes = dict(EditorHost._scenes)
    orig_active = EditorHost._active_scene
    orig_cb = _ev.app_callback_func
    st = SceneManager("EditorHost")
    SceneManager._registry["EditorHost"] = st
    EditorHost.scene = st
    EditorHost._scenes = {}
    EditorHost._active_scene = None
    _ev.app_callback_func = lambda _e: None  # headless: 吞事件派发 (NewComponentEvent 等)

    created: list[int] = []
    try:
        # ── 3. 选中链 ──
        e1 = SceneBrowserController.add_entity("GuardA")
        created.append(e1)
        check("entity.add → 自动选中 (数据层)", SceneBrowserController.get_selected() == e1)
        check("entity.add → gizmo 隐藏 (plain select)", TransformGizmo._visible is False)

        SelectionController.select_with_gizmo(e1)
        check("select_with_gizmo → gizmo 可见 + 目标正确",
              TransformGizmo._visible is True and TransformGizmo._target_entity_id == e1,
              f"visible={TransformGizmo._visible} target={TransformGizmo._target_entity_id}")

        SelectionController.select(e1)
        check("select (plain) → gizmo 隐藏", TransformGizmo._visible is False)

        # ── 4. add 子级 / delete 级联 ──
        e2 = SceneBrowserController.add_entity("GuardChild")
        created.append(e2)
        check("add → 成为选中实体子级", SceneBrowserController.get_entity_parent(e2) == e1)
        check("add → 选中切换到新实体", SelectionController.get_selected() == e2)

        SelectionController.select_with_gizmo(e2)
        SceneBrowserController.delete_entity(e1)   # 删父 → 子 e2 一并删除
        check("删祖先 → 选中级联清理 (数据层)",
              SceneBrowserController.get_selected() is None)
        check("删祖先 → gizmo 隐藏", TransformGizmo._visible is False)
        created = [e for e in created if e not in (e1, e2)]

        e3 = SceneBrowserController.add_entity("GuardB")
        created.append(e3)
        SceneBrowserController.delete_entity(e3)   # 删选中自身
        check("删选中自身 → 选中清理", SelectionController.get_selected() is None)
        created.remove(e3)

        # ── 5. 场景切换 / 新建 ──
        sa = Scene("Guard_A")
        sb = Scene("Guard_B")
        EditorHost._scenes = {"Guard_A": sa, "Guard_B": sb}
        EditorHost._active_scene = sa
        e4 = SceneBrowserController.add_entity("GuardC")
        check("场景前置: 有选中", SelectionController.get_selected() == e4)

        ok = EditorHost.switch_scene("Guard_B")
        check("switch_scene True + 选中清理",
              ok is True and SelectionController.get_selected() is None)
        check("switch_scene → active 切换", EditorHost.get_active_scene() is sb)

        EditorHost.create_scene("Guard_C")
        check("create_scene → 新场景成为活跃",
              EditorHost.get_active_scene() is EditorHost._scenes.get("Guard_C"))
        check("create_scene → 选中仍为清空态",
              SelectionController.get_selected() is None)
    finally:
        for _eid in created:
            try:
                st.DeleteEntity(_eid)
            except Exception:
                pass
        _ev.app_callback_func = orig_cb
        EditorHost.scene = orig_scene_attr
        EditorHost._scenes = orig_scenes
        EditorHost._active_scene = orig_active
        if orig_reg is None:
            SceneManager._registry.pop("EditorHost", None)
        else:
            SceneManager._registry["EditorHost"] = orig_reg

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
