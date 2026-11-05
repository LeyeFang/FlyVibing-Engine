"""生成 `Examples/UIShowcase` — 运行期 UI 组件的长期测试工程（可重复执行）。

四重身份（协议：`Doc/Dev/product_todo.md` §10.8）:
  1. `File ▸ Open Example` 的人工演示；
  2. core 守卫（`Test/Application/Core/test_ui_showcase.py` 校验控件齐全/token 可解析）；
  3. live e2e（PIE 截图 + overlay 捕获/穿透探针）；
  4. 用户模板（复制即用）。

用法（仓库根）:
    .venv-py314t\\Scripts\\python.exe Examples\\tools\\build_ui_showcase.py

约定:
  - 所有尺寸写在参考分辨率 1920x1080 里（`UICanvas.scale_mode = contain` —
    宽高都贴合，编辑器窄视口 / 超宽屏都不会裁掉内容）；
  - 颜色/字号只写主题 token（`@color.*` / `@font.size.*`），不写死 RGB；
  - 退出确认对话框 `role="exit_confirm"` + `visible=False`（ESC 打开）；
  - 每个 UI 实体都带 `Transform`（编辑器 Outliner / 其它系统按 Transform 枚举实体）。
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Application.Core.Scene.BasicComponents import Transform  # noqa: E402
from Application.Core.Scene.Scene import GameType, Scene  # noqa: E402
from Application.Core.Scene.UIComponents import (  # noqa: E402
    UICanvas,
    UIButton,
    UILabel,
    UIPanel,
    UIRect,
    UISelect,
    UISlider,
    UIToggle,
)

OUT_DIR = os.path.join(ROOT, "Examples", "UIShowcase")
SCENE_PATH = os.path.join(OUT_DIR, "scenes", "UIShowcase.scene")
PROJECT_PATH = os.path.join(OUT_DIR, "UIShowcase.myproj")


def _rect(anchor="center", pos=(0.0, 0.0), size=(0.0, 0.0), *,
          visible=True, order=0) -> UIRect:
    return UIRect(anchor=anchor, pivot=anchor,
                  pos_x=float(pos[0]), pos_y=float(pos[1]),
                  width=float(size[0]), height=float(size[1]),
                  visible=bool(visible), order=int(order))


def _panel(anchor="center", pos=(0.0, 0.0), size=(0.0, 0.0), *,
           bg="@color.surface", border="@color.border", border_w=1.0,
           scrim="", modal=False, role="", visible=True, order=0) -> dict:
    return {
        "UIRect": _rect(anchor, pos, size, visible=visible, order=order),
        "UIPanel": UIPanel(bg_color=bg, border_color=border, border_width=border_w,
                           scrim_color=scrim, modal=modal, role=role),
    }


def _label(anchor="center", pos=(0.0, 0.0), size=(0.0, 0.0), *, text="",
           font_size=28.0, color="@color.text", align="center", bold=False,
           visible=True, order=0) -> dict:
    return {
        "UIRect": _rect(anchor, pos, size, visible=visible, order=order),
        "UILabel": UILabel(text=text, size=font_size, color=color,
                           align=align, bold=bold),
    }


def _button(anchor="center", pos=(0.0, 0.0), size=(200.0, 64.0), *, text="",
            variant="secondary", action="", enabled=True, font_size=0.0,
            visible=True, order=0) -> dict:
    return {
        "UIRect": _rect(anchor, pos, size, visible=visible, order=order),
        "UIButton": UIButton(text=text, variant=variant, action=action,
                             enabled=enabled, size=font_size),
    }


def _toggle(anchor="center", pos=(0.0, 0.0), size=(0.0, 56.0), *, label="",
            value=False, action="", visible=True, order=0) -> dict:
    return {
        "UIRect": _rect(anchor, pos, size, visible=visible, order=order),
        "UIToggle": UIToggle(label=label, value=bool(value), action=action),
    }


def _slider(anchor="center", pos=(0.0, 0.0), size=(0.0, 56.0), *, label="",
            min_value=0.0, max_value=1.0, step=0.0, value=0.0,
            show_value=True, action="", visible=True, order=0) -> dict:
    return {
        "UIRect": _rect(anchor, pos, size, visible=visible, order=order),
        "UISlider": UISlider(label=label, min_value=float(min_value),
                             max_value=float(max_value), step=float(step),
                             value=float(value), show_value=bool(show_value),
                             action=action),
    }


def _select(anchor="center", pos=(0.0, 0.0), size=(0.0, 56.0), *, label="",
            options=(), index=0, skin="segmented", action="",
            visible=True, order=0) -> dict:
    return {
        "UIRect": _rect(anchor, pos, size, visible=visible, order=order),
        "UISelect": UISelect(label=label, options=tuple(options), index=int(index),
                             skin=skin, action=action),
    }


def _build_graph(scene: Scene) -> None:
    """小节点图：OnGameStart 隐藏 NodeHint；OnUIClick(show:DetailPanel)
    显示它并把 DetailTitle 改成运行期文本。

    演示“节点图驱动 UI 显隐 + 文本”（协议：`Doc/Dev/runtime_ui_protocol.md` §5）。
    """
    from Application.Core.NodeGraph.canvas import NodeCanvas

    canvas = NodeCanvas()
    start = canvas.add_node("OnGameStart", (-520.0, -160.0))
    hide = canvas.add_node("SetUIVisible", (-200.0, -160.0))
    click = canvas.add_node("OnUIClick", (-520.0, 80.0))
    show = canvas.add_node("SetUIVisible", (-200.0, 80.0))
    retitle = canvas.add_node("SetUIText", (120.0, 80.0))
    if min(start, hide, click, show, retitle) < 0:
        raise RuntimeError("UI nodes are not registered")

    canvas.nodes[hide].props.update({"target": "NodeHint", "visible": False})
    canvas.nodes[show].props.update({"target": "NodeHint", "visible": True})
    canvas.nodes[click].props.update({"action": "show:DetailPanel"})
    canvas.nodes[retitle].props.update({"target": "DetailTitle",
                                        "text": "Trial 1 / 12"})

    canvas.add_link(canvas.nodes[start].pin_ids["exec"],
                    canvas.nodes[hide].pin_ids["exec_in"])
    canvas.add_link(canvas.nodes[click].pin_ids["exec"],
                    canvas.nodes[show].pin_ids["exec_in"])
    canvas.add_link(canvas.nodes[show].pin_ids["exec_out"],
                    canvas.nodes[retitle].pin_ids["exec_in"])
    scene.node_graph = canvas


def build_scene() -> Scene:
    scene = Scene(name="UIShowcase", game_type=GameType.GAME_3D)

    # ── 画布（参考分辨率 + 等比缩放）──
    canvas = scene.add_entity(
        "UIHUD", Transform=Transform(),
        UICanvas=UICanvas(scale_mode="contain", reference_w=1920,
                          reference_h=1080, sort_order=0, visible=True))

    def add(parent, name, comps):
        eid = scene.add_entity(name, Transform=Transform(), **comps)
        scene.entities[eid].parent_id = parent
        return eid

    # ── 1. 顶部栏：面板 + 左右对齐的两个文字 ──
    bar = add(canvas, "TopBar", _panel("top", (0.0, 0.0), (0.0, 110.0),
                                       bg="@color.surface", border_w=0.0))
    add(bar, "TopBarTitle", _label("left", (36.0, 0.0), (1200.0, 110.0),
                                   text="UI Showcase", font_size=44.0,
                                   align="left", bold=True))
    add(bar, "TopBarHint", _label("right", (-36.0, 0.0), (1100.0, 110.0),
                                  text="Esc = exit confirm | reference 1920x1080",
                                  font_size=22.0, color="@color.text.muted",
                                  align="right"))

    # ── 2. 控制面板：标题 + 5 个按钮变体（两行）+ 脚注 ──
    ROW_W = 844.0          # 面板内边距 28（参考像素）
    controls = add(canvas, "ControlsPanel",
                   _panel("left", (40.0, -150.0), (900.0, 380.0)))
    add(controls, "ControlsTitle", _label("top", (0.0, 22.0), (ROW_W, 56.0),
                                          text="Controls", font_size=36.0))
    add(controls, "ControlsSubtitle", _label(
        "top", (0.0, 82.0), (ROW_W, 40.0),
        text="Colors come from theme tokens - nothing hardcoded in the scene",
        font_size=22.0, color="@color.text.muted"))
    add(controls, "BtnPrimary", _button("top", (-240.0, 150.0), (220.0, 64.0),
                                        text="Primary", variant="primary",
                                        action="show:DetailPanel"))
    add(controls, "BtnSecondary", _button("top", (0.0, 150.0), (220.0, 64.0),
                                          text="Secondary",
                                          action="toggle:DetailPanel"))
    add(controls, "BtnDanger", _button("top", (240.0, 150.0), (220.0, 64.0),
                                       text="Danger", variant="danger"))
    add(controls, "BtnGhost", _button("top", (-120.0, 240.0), (220.0, 64.0),
                                      text="Ghost", variant="ghost"))
    add(controls, "BtnDisabled", _button("top", (120.0, 240.0), (220.0, 64.0),
                                         text="Disabled", enabled=False))
    add(controls, "ControlsNote", _label(
        "bottom", (0.0, -18.0), (ROW_W, 32.0),
        text="Primary = show detail | Secondary = toggle detail",
        font_size=20.0, color="@color.text.muted"))

    # ── 2b. 设置面板：开关 / 滑条 / 离散选择三皮肤 ──
    settings = add(canvas, "SettingsPanel",
                   _panel("left", (40.0, 270.0), (900.0, 420.0)))
    add(settings, "SettingsTitle", _label("top", (0.0, 20.0), (ROW_W, 52.0),
                                          text="Settings", font_size=36.0))
    add(settings, "SetToggle", _toggle("top", (0.0, 84.0), (ROW_W, 56.0),
                                       label="Sound", value=True))
    add(settings, "SetVolume", _slider("top", (0.0, 146.0), (ROW_W, 56.0),
                                       label="Volume", min_value=0.0,
                                       max_value=100.0, step=5.0, value=60.0))
    add(settings, "SetQuality", _select("top", (0.0, 208.0), (ROW_W, 56.0),
                                        label="Quality",
                                        options=("Low", "Medium", "High"),
                                        index=1, skin="segmented"))
    add(settings, "SetResolution", _select("top", (0.0, 270.0), (ROW_W, 56.0),
                                           label="Resolution",
                                           options=("1280x720", "1920x1080",
                                                    "2560x1440"),
                                           index=1, skin="stepper"))
    add(settings, "SetTheme", _select("top", (0.0, 332.0), (ROW_W, 56.0),
                                      label="Theme",
                                      options=("Dark", "Light", "High contrast"),
                                      index=0, skin="dropdown"))

    # ── 3. 详情浮窗：标题 + 正文 + Close（action=close 关自己的面板）──
    detail = add(canvas, "DetailPanel",
                 _panel("right", (-40.0, 0.0), (460.0, 360.0)))
    add(detail, "DetailTitle", _label("top", (0.0, 28.0), (400.0, 48.0),
                                      text="Detail panel", font_size=32.0))
    add(detail, "DetailBody", _label(
        "top", (0.0, 96.0), (400.0, 90.0),
        text="Toggle with Secondary.\nEsc opens the exit dialog.",
        font_size=22.0, color="@color.text.muted"))
    add(detail, "NodeHint", _label(
        "top", (0.0, 196.0), (400.0, 80.0),
        text="Shown by the node graph\n(OnUIClick -> SetUIVisible)",
        font_size=20.0, color="@color.text.muted"))
    add(detail, "DetailClose", _button("bottom", (0.0, -28.0), (160.0, 56.0),
                                       text="Close", action="close"))

    # ── 4. 退出确认对话框（ESC 打开；模态 + 遮罩；默认隐藏）──
    quit_panel = add(canvas, "ExitDialog",
                     _panel("center", (0.0, 0.0), (620.0, 320.0),
                            scrim="@color.scrim", modal=True,
                            role="exit_confirm", visible=False))
    add(quit_panel, "ExitTitle", _label("top", (0.0, 44.0), (560.0, 56.0),
                                        text="Exit game?", font_size=42.0))
    add(quit_panel, "ExitHint", _label(
        "top", (0.0, 116.0), (560.0, 40.0),
        text="Esc / Stay = keep playing | Exit = quit",
        font_size=22.0, color="@color.text.muted"))
    add(quit_panel, "ExitStay", _button("center", (-112.0, 88.0), (200.0, 64.0),
                                        text="Stay", action="close"))
    add(quit_panel, "ExitQuit", _button("center", (112.0, 88.0), (200.0, 64.0),
                                        text="Exit", variant="primary",
                                        action="exit"))
    _build_graph(scene)
    return scene


PROJECT = {
    "version": "0.1.0",
    "name": "UIShowcase",
    "provider": "@Official",
    "startup_scene": "scenes\\UIShowcase.scene",
    "scenes": ["scenes\\UIShowcase.scene"],
    "background_color": [0.07, 0.08, 0.10],
    "resources": {
        "materials": [],
        "shaders": [],
        "textures": [],
        "meshes": [],
        "prefabs": [
            {"path": "builtin://DefaultCamera3D"},
            {"path": "builtin://DefaultCamera2D"},
            {"path": "builtin://DefaultCameraOverlay"},
            {"path": "builtin://DefaultCube"},
            {"path": "builtin://DefaultLight"},
        ],
    },
}


def main() -> int:
    scene = build_scene()
    os.makedirs(os.path.dirname(SCENE_PATH), exist_ok=True)
    scene.save_to_file(SCENE_PATH)
    with open(PROJECT_PATH, "w", encoding="utf-8") as fh:
        json.dump(PROJECT, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    ui_entities = [ed for ed in scene.entities.values()
                   if any(k.startswith("UI") for k in ed.components)]
    print(f"[UIShowcase] entities={len(scene.entities)}  ui={len(ui_entities)}")
    print(f"[UIShowcase] scene   -> {SCENE_PATH}")
    print(f"[UIShowcase] project -> {PROJECT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
