"""
ControllerRegistry — 编辑器 UI 控制器注册表。

职责:
  - 解耦 Panel 与具体 Controller 类之间的硬绑定
  - 支持测试时注入 Mock Controller 替换真 Controller
  - 保持现有 @classmethod 单例风格不受影响

使用方式:

  生产代码:
    # 各 Controller 模块末尾注册自身
    from Application.Editor.Services.ControllerRegistry import register
    register("Simulation", SimulationController)

    # Panel 中从注册表获取
    from Application.Editor.Services.ControllerRegistry import get_ctrl
    sim = get_ctrl("Simulation")
    sim.play()

  测试代码:
    from Application.Editor.Services.ControllerRegistry import register
    register("Simulation", MockSimulationController)  # 替换为 Mock
    panel = ScenePanel()  # panel 内部 get_ctrl("Simulation") 拿到 Mock

架构约束:
  ✅ Panel 可引用: ControllerRegistry, imgui
  ❌ ControllerRegistry 不可引用: imgui, Panel
"""

from __future__ import annotations

from typing import Optional

# ── 全局注册表 ─────────────────────────────────────────────────
_registry: dict[str, type] = {}

# ── 已知的 Controller 名称（便于自动补全 & 拼写检查） ──────────

NAME_SIMULATION     = "Simulation"
NAME_SCENE_BROWSER  = "SceneBrowser"
NAME_RESOURCE_BROWSER = "ResourceBrowser"
NAME_VIEWPORT       = "Viewport"
NAME_NODE_EDITOR    = "NodeEditor"
NAME_SELECTION      = "Selection"


# ═══════════════════════════════════════════════════════════════
# 注册 / 查询 / 重置
# ═══════════════════════════════════════════════════════════════

def register(name: str, controller_cls: type) -> None:
    """注册一个 Controller 类到全局注册表。

    Args:
        name: Controller 名称（建议使用 NAME_* 常量）
        controller_cls: Controller 类（通常为 @classmethod 单例风格的类）
    """
    _registry[name] = controller_cls


def get_ctrl(name: str) -> Optional[type]:
    """从注册表获取 Controller 类。

    Args:
        name: Controller 名称

    Returns:
        Controller 类，若未注册则返回 None
    """
    return _registry.get(name)


def reset() -> None:
    """清空注册表 — 仅供测试使用。

    每个测试应在 tearDown 中调用此函数，
    确保测试间的 Mock 注入不互相污染。
    """
    _registry.clear()
