from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Core.Engine import Engine

from Application.Core.Events.Event import Event

from abc import ABC, abstractmethod


# ════════════════════════════════════════════════════════════════
# 常见分辨率表（宽 x 高，按面积降序排列）
# ════════════════════════════════════════════════════════════════

# 4:3 分辨率（从最大到最小）
RES_4_3: list[tuple[int, int]] = [
    (2048, 1536),   # QXGA
    (1920, 1440),   # — 常见 4:3 高端
    (1600, 1200),   # UXGA
    (1440, 1080),   # — 常见 4:3
    (1400, 1050),   # SXGA+
    (1280, 1024),   # SXGA  (严格 5:4，但通常归为近似 4:3)
    (1280, 960),    # — 标准 4:3
    (1152, 864),    # XGA+
    (1024, 768),    # XGA
    (800, 600),     # SVGA
    (640, 480),     # VGA
]

# 16:9 分辨率（从最大到最小）
RES_16_9: list[tuple[int, int]] = [
    (3840, 2160),   # 4K UHD
    (2560, 1440),   # WQHD
    (1920, 1080),   # Full HD
    (1600, 900),    # HD+
    (1366, 768),    # 常见笔记本
    (1280, 720),    # HD
]

# 16:10 分辨率
RES_16_10: list[tuple[int, int]] = [
    (2560, 1600),   # WQXGA
    (1920, 1200),   # WUXGA
    (1680, 1050),   # WSXGA+
    (1440, 900),    # WXGA+
    (1280, 800),    # WXGA
]

# 统一映射：aspect_name -> (aspect_ratio, resolution_list)
ASPECT_RES_MAP: dict[str, tuple[float, list[tuple[int, int]]]] = {
    "4:3":  (4.0 / 3.0, RES_4_3),
    "16:9": (16.0 / 9.0, RES_16_9),
    "16:10": (16.0 / 10.0, RES_16_10),
}


class Window(ABC):

    app = None
    window = None

    # ── 所属 Engine (由 Engine.init() 在创建窗口后设置) ──
    _engine: type = None

    # ── 窗口默认尺寸（由分辨率选择逻辑覆写） ──
    _window_width: int = 800
    _window_height: int = 600

    @classmethod
    @abstractmethod
    def Create(cls, app: Application):
        ...

    @classmethod
    @abstractmethod
    def Update(cls):
        ...

    @classmethod
    @abstractmethod
    def Therminate(cls):
        ...

    @classmethod
    @abstractmethod
    def GetSize(cls):
        ...

    @classmethod
    @abstractmethod
    def OnEvent(cls, event: Event):
        ...

    # ════════════════════════════════════════════════════════════
    # 分辨率选择工具（后端无关）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _get_system_resolution(cls) -> tuple[int, int]:
        """获取主显示器当前分辨率 — 由子类（后端）覆盖实现。

        Returns:
            (width, height) 像素。默认返回 (1920, 1080) 作为安全回退。
        """
        return 1920, 1080

    @classmethod
    def _detect_aspect(cls, width: int, height: int) -> str | None:
        """检测分辨率最接近哪个已知比例桶。

        比较 width/height 与 ASPECT_RES_MAP 中各比例的差值，
        取差值最小且 < 5% 的那一个。

        Returns:
            比例键名如 "16:9"，或 None（无法匹配）。
        """
        if height == 0:
            return None
        ratio = width / height
        best_name: str | None = None
        best_diff = float('inf')
        for name, (target_ratio, _) in ASPECT_RES_MAP.items():
            diff = abs(ratio - target_ratio)
            if diff < best_diff:
                best_diff = diff
                best_name = name
        return best_name if best_diff < 0.05 else None

    @classmethod
    def _pick_optimal_resolution(
        cls,
        system_width: int,
        system_height: int,
    ) -> tuple[int, int]:
        """检测系统分辨率所属比例，取「小一圈」的标准分辨率。

        策略:
          1. 自动检测系统分辨率的宽高比（16:9 / 16:10 / 4:3 …）
          2. 在对应标准分辨率表中，找到第一个比系统分辨率**严格小**的项
             （即 w < system_width 且 h < system_height）
          3. 如果表中没有更小的，取该比例的最小分辨率兜底

        Args:
            system_width:  系统当前分辨率宽度（像素）
            system_height: 系统当前分辨率高度（像素）

        Returns:
            (width, height) 选中的窗口分辨率
        """
        aspect = cls._detect_aspect(system_width, system_height)
        if aspect is None:
            return cls._window_width, cls._window_height

        _, resolutions = ASPECT_RES_MAP[aspect]

        # ── 找第一个严格小于系统分辨率的项 ────────────────
        for w, h in resolutions:
            if w < system_width and h < system_height:
                return w, h

        return resolutions[-1]

    @classmethod
    def _compute_default_size(cls) -> tuple[int, int]:
        """便捷方法：获取系统分辨率 → 选取小一圈分辨率 → 缓存并返回。

        Returns:
            (width, height)
        """
        sys_w, sys_h = cls._get_system_resolution()
        w, h = cls._pick_optimal_resolution(sys_w, sys_h)
        cls._window_width, cls._window_height = w, h
        return w, h

