"""
Test: Live UI — 主线面板实时渲染测试
═══════════════════════════════════════════════════════════════════════════════

直接复用主线 ScenePanel 和 NodeEditorPanel，渲染完整的编辑器 UI。
纯 ImGui，无 3D 渲染，无 gizmo，无 transform 交互。

用途:
  - 实时预览主线 UI 面板的视觉改动（颜色 / 字体 / 间距 / 布局）
  - 验证面板级交互（标签页切换、实体选择、节点编辑）
  - 无需启动完整 EditorHost，秒级迭代 UI

与 test_editor_gui.py 的区别:
  test_editor_gui.py → 手写桩面板（假数据，不随主线更新）
  test_live_ui.py    → 复用主线 Panel 类（真实数据，随主线自动更新）

脚本化/快照方案: `ui_scenario.py`（同一引导 `_ui_boot.py`; 场景回放 + PNG 快照; `--preview` 即本程序用法）。

引导层:
  GLFW 窗口 + ResourceManager + SceneManager + Mock EditorCamera
  → 刚好让 Controller 不崩溃，但不过度初始化引擎

运行: python Test/Application/Editor/test_live_ui.py
退出: ESC
"""

from __future__ import annotations
import sys, os, ctypes

# ── 路径引导（同其他 Test 文件） ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import glfw
from imgui_bundle import imgui
from OpenGL import GL as gl

# ── 引擎最小引导（共享: _ui_boot — 自包含, 不依赖 Test._test_harness/pyrr）──
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer
from _ui_boot import UiBoot


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def _create_test_entities(num: int = 3) -> list[int]:
    """创建少量测试 Entity，让 ScenePanel 的 Entities 标签页有数据可显示。"""
    cube_mesh_id = ResourceManager.GetDefaultMesh('Cube')
    positions = [
        (-3.0, 0.0, -6.0),
        ( 0.0, 0.0, -6.0),
        ( 3.0, 0.0, -6.0),
    ][:num]

    entity_ids = []
    scene = SceneManager._current()
    for pos in positions:
        eid = scene.AddEntity()
        scene.AddComponentToEntity(eid, MeshRenderer(mesh_id=cube_mesh_id))
        scene.SetEntityTransform(eid, position_xyz=pos)
        entity_ids.append(eid)
    return entity_ids


def _load_font(io) -> None:
    """加载字体 + Font Awesome 6 图标 — 与主线 EditorLayer 相同。"""
    from imgui_bundle import hello_imgui as _hi

    _resource_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "Resource"))
    _hi.set_assets_folder(_resource_dir)

    font_candidates = [
        "Fonts/Inter-Regular.ttf",
        "Fonts/segoeui.ttf",
        "Fonts/arial.ttf",
    ]
    for rel_path in font_candidates:
        if _hi.asset_exists(rel_path):
            _hi.load_font_ttf_with_font_awesome_icons(rel_path, 17.0)
            return
    # 回退: 使用 imgui 内置等宽字体
    io.fonts.add_font_default()


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ── 共享引导（窗口 + 子系统 + imgui + 面板注册; 见 _ui_boot.py）──
    boot = UiBoot(hidden=False, title="Live UI — Mainline Panels (ESC to exit)").create()

    # 创建测试 Entity — ScenePanel 会显示它们
    entity_ids = _create_test_entities(3)
    print(f"[Live UI] Created {len(entity_ids)} test entities: {entity_ids}")

    print("[Live UI] Ready — ESC to exit")
    print("  Panels  : Scene (real data), Node Editor (real canvas)")
    print("  Theme   : Blender dark (applied by UIManager)")
    print("  No 3D   : no openGLRenderer, no Grid, no ViewGizmo, no OutlinerID")
    print("  Control : SimulationController is live but engine is minimal (Play won't fully start)")

    # ── 主循环 ──
    while not glfw.window_should_close(boot.window):
        boot.frame()
        # ESC 退出
        if imgui.is_key_pressed(imgui.Key.escape, False):
            glfw.set_window_should_close(boot.window, True)

    boot.close()
    print("[Live UI] Done")


if __name__ == "__main__":
    main()
