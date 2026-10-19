"""EditorSettings — 编辑器全局设置服务（单一读写入口）。

协议: `Doc/Dev/ui_protocol.md` §13（Settings 面板与设置体系）。

存储: `Application/Editor/Config/settings.json`（env `MGE_EDITOR_SETTINGS` 可覆盖 — 测试沙箱）

键位（首版）:
  - `"ui.font_scale"`  float, clamp **0.7..1.6** — UI 字体缩放（imgui `style.font_scale_main`）
  - `"ui.language"`    语言代码 — 由 `Locale/*.json` 目录动态推导（默认 `en`;
                       协议 `Doc/Dev/i18n_protocol.md` §5）

线程模型（free-threaded）:
  - 任意线程可读 `get`；`set` 以锁保护并在锁内落盘（低频）;
  - **应用**（改 imgui style / 切语言）**只在渲染线程帧首**执行 —
    `apply_pending()` 由 `EditorImguiLayer.OnRender` 每帧调用（style 是渲染线程资产）;
  - 测试可用 `_reset_for_tests()` 重置单例状态。
"""

from __future__ import annotations

from Application.Core import AppIdentity

import json
import os
import threading
import traceback
from typing import Callable, Optional

DEFAULTS: dict = {
    "ui.font_scale": 1.0,
    "ui.language": "en",
}

# 数值 clamp: key → (min, max)；枚举: key → 允许值集合（单一权威 — 与 Settings 面板选择集一致）
CLAMPS: dict = {
    "ui.font_scale": (0.7, 1.6),
}
CHOICES: dict = {
    "ui.language": ("en",),   # 兜底值; 运行期由已发布语言目录动态推导（_allowed_choices）
}


def _allowed_choices(key: str) -> tuple:
    """枚举键允许值 — `ui.language` 由语言目录动态推导（协议 `Doc/Dev/i18n_protocol.md` §5）。

    新增语言只改 `Locale/<lang>.json` → 设置枚举/面板选项自动跟随；
    目录不可用（无头/异常）时回退静态 `CHOICES`，不阻塞。
    """
    if key == "ui.language":
        try:
            from Application.Editor.I18n import available_languages
            langs = tuple(available_languages())
            if langs:
                return langs
        except Exception:  # noqa: BLE001 — 无目录环境回退静态表
            pass
    return CHOICES[key]



class EditorSettings:
    """类级单例（编辑器应用层）。"""

    _values: dict = dict(DEFAULTS)
    _pending: set = set()
    _lock = threading.Lock()
    _loaded: bool = False

    # 应用回调（渲染线程）— 可注入替换（测试）; 默认惰性指向真实实现
    _apply_hooks: dict = {}

    # ── 路径 ────────────────────────────────────────────────────

    @classmethod
    def path(cls) -> str:
        env = AppIdentity.env_get("EDITOR_SETTINGS")
        if env:
            return env
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "Config", "settings.json")

    # ── 读 ─────────────────────────────────────────────────────

    @classmethod
    def load(cls) -> dict:
        """从磁盘载入（缺文件/损坏 → 默认值容错）。"""
        data: dict = {}
        try:
            with open(cls.path(), encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                data = raw
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001 — 损坏设置不致命
            print(f"[Settings] load failed (using defaults): {e!r}")
        with cls._lock:
            for key, default in DEFAULTS.items():
                cls._values[key] = cls._coerce(key, data.get(key, default))
            cls._loaded = True
        return cls.all()

    @classmethod
    def get(cls, key: str, default=None):
        with cls._lock:
            return cls._values.get(key, DEFAULTS.get(key, default))

    @classmethod
    def all(cls) -> dict:
        with cls._lock:
            return dict(cls._values)

    # ── 写 ─────────────────────────────────────────────────────

    @classmethod
    def set(cls, key: str, value) -> object:
        """写入设置（类型/范围校验 → 落盘 → 入 pending，由渲染线程应用）。

        Returns: 实际写入的值（已钳制）。
        Raises: KeyError — 未知键（不静默创建任意键）。
        """
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting key: {key!r} (known: {', '.join(sorted(DEFAULTS))})")
        coerced = cls._coerce(key, value)
        with cls._lock:
            cls._values[key] = coerced
            cls._pending.add(key)
            snapshot = dict(cls._values)
        cls._save(snapshot)
        return coerced

    @classmethod
    def _coerce(cls, key: str, value):
        """类型 + 范围/枚举校验（钳制而非报错 — 与 FIELD_CLAMPS 同风格）。"""
        if key in CLAMPS:
            lo, hi = CLAMPS[key]
            try:
                return max(lo, min(hi, float(value)))
            except (TypeError, ValueError):
                return DEFAULTS[key]
        if key in CHOICES:
            return value if value in _allowed_choices(key) else DEFAULTS[key]
        return value

    @classmethod
    def _save(cls, snapshot: dict) -> None:
        try:
            path = cls.path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            print(f"[Settings] save failed: {e!r}")

    # ── 应用（渲染线程帧首） ────────────────────────────────────

    @classmethod
    def register_apply_hook(cls, key: str, fn: Callable[[object], None]) -> None:
        """注入某键的应用回调（渲染线程调用）— 测试可替换为探针。"""
        cls._apply_hooks[key] = fn

    @classmethod
    def apply_pending(cls) -> list:
        """应用挂起的设置变更（渲染线程帧首调用）; 返回已应用键列表。

        帧内零分配稳态: 无 pending 时仅一次加锁判断。
        """
        with cls._lock:
            keys = sorted(cls._pending)
            cls._pending.clear()
            values = {k: cls._values.get(k) for k in keys}
        for key in keys:
            cls._apply_one(key, values.get(key))
        return keys

    @classmethod
    def apply_all(cls) -> None:
        """全量应用（启动时由 EditorImguiLayer.OnAttach 调用）。"""
        for key, value in cls.all().items():
            cls._apply_one(key, value)

    @classmethod
    def _apply_one(cls, key: str, value) -> None:
        hook = cls._apply_hooks.get(key)
        if hook is not None:
            try:
                hook(value)
            except Exception:  # noqa: BLE001 — 应用失败不拖垮帧
                traceback.print_exc()
            return
        if key == "ui.font_scale":
            try:
                from Application.Editor.EditorImguiLayer import EditorImguiLayer
                EditorImguiLayer.apply_font_scale(float(value))
            except Exception:  # noqa: BLE001 — 无 imgui 环境（无头）跳过
                pass
        elif key == "ui.language":
            try:
                from Application.Editor.I18n import set_language
                set_language(str(value))
            except Exception:  # noqa: BLE001
                pass

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._lock:
            cls._values = dict(DEFAULTS)
            cls._pending.clear()
            cls._loaded = False
        cls._apply_hooks = {}
