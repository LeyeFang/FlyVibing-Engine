"""
EditorPlugin — 编辑器插件（Plugin 实现）。

职责:
  - 暴露编辑器 Layer: EditorLayer（3D 视口+面板）、DebugLayer（调试 HUD）
  - 插件级初始化/清理（未来 ImGui 上下文管理等从 EditorLayer 搬来）

生命周期:
  EditorHost.init() → EditorHost.load_plugin(EditorPlugin())
    ├── EditorPlugin.on_load(engine)
    └── Engine.push_layer(EditorLayer)
        Engine.push_layer(DebugLayer)

  EditorHost.run() → ... → EditorHost.shutdown()
    └── EditorPlugin.on_unload()

过渡期说明:
  当前 ImGui 上下文创建、字体加载、GLFW/OpenGL3 backend 初始化
  仍在 EditorLayer.OnAttach()（渲染线程）中处理。
  EditorPlugin 现阶段是 Layer 注册器 — 定义编辑器有哪些帧级 Layer。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Application.Core.Plugin import Plugin
from Application.Core.Layers.Layer import Layer

if TYPE_CHECKING:
    from Application.Core.Engine import Engine


class EditorPlugin(Plugin):
    """编辑器插件 — 管理所有编辑器 UI 子系统的加载/卸载。"""

    name: str = "EditorPlugin"
    version: str = "0.1.0"

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    def on_load(self, engine: 'Engine') -> None:
        """编辑器插件加载（主线程）。"""
        # ── 实时命令总线（agent MCP 热注入; 仅本机回环 127.0.0.1）──
        try:
            from Application.Editor.Services.LiveCommandServer import LiveCommandServer
            LiveCommandServer.start()
        except Exception as e:  # noqa: BLE001
            print(f"[Live] command server failed to start: {e}")

    def on_unload(self) -> None:
        """编辑器插件卸载（主线程）。"""
        try:
            from Application.Editor.Services.LiveCommandServer import LiveCommandServer
            LiveCommandServer.stop()
        except Exception:  # noqa: BLE001
            pass

    # ════════════════════════════════════════════════════════════
    # Layer 暴露
    # ════════════════════════════════════════════════════════════

    def get_layers(self) -> list[type[Layer]]:
        """返回编辑器插件拥有的 Layer 类（按 OnAttach 执行顺序）。

        EditorImguiLayer → ImGui 上下文 / 字体 / Backend / 面板 (必须在最前)
        EditorLayer      → 渲染器接入 / overlay 注册 / 层间连线
        EditorGizmoLayer → Camera entity gizmo 可视化 / 预览切换
        EditorInputLayer → 输入事件路由 (鼠标/键盘/滚轮/窗口)
        DebugLayer       → 性能 HUD + 场景调试实体
        """
        from Application.Editor.EditorImguiLayer import EditorImguiLayer
        from Application.Editor.EditorLayer import EditorLayer
        from Application.Editor.EditorGizmoLayer import EditorGizmoLayer
        from Application.Editor.EditorInputLayer import EditorInputLayer
        from Application.Editor.EditorDebugLayer import DebugLayer
        return [EditorImguiLayer, EditorLayer, EditorGizmoLayer, EditorInputLayer, DebugLayer]
