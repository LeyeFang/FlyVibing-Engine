"""RuntimeUILayer — 运行时 UI 层（场景驱动的 `UICanvas/UIRect/UIPanel/UILabel/UIButton`）。

职责边界（协议：`Doc/Dev/product_todo.md` §10）:
  - **呈现**：每帧把场景 UI 元素编译成 `UIQuad` 交给渲染器（`OpenGLUI` 负责画）；
  - **命中**：矩形数学（`Core/UI/tree.py`），不用 GPU pick；
  - **模态**：`UIPanel(modal=True)` 打开时**消费**所有键鼠，节点图看不到；
  - **动作**：`UIButton.action` → `exit` / `close` / `show:名` / `hide:名` / `toggle:名`；
  - **ESC 策略**：优先打开场景里 `UIPanel(role="exit_confirm")` 的面板；
    场景没有该面板时退回**内置对话框**（无 UI 场景 / 第三方工程仍可用）。

线程模型:
  - `OnUpdate`（逻辑线程）读 ECS → 不可变 `UIElement` 快照；
  - `OnRender`（渲染线程）只读快照 → 编译 quad（**渲染线程不碰 esper**）；
  - `OnEvent`（窗口事件线程）只改交互状态（hover/press/override）。

它不依赖 Editor（PIE 与导出成品共用）；内置对话框文案由宿主注入（编辑器侧用 i18n）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace

from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import (
    KeyboardButtonEvent,
    MouseButtonEvent,
    MouseMoveEvent,
)
from Application.Core.Events.WindowEvent import WindowCloseEvent
from Application.Core.Layers.Layer import Layer
from Application.Core.UI.controls import (
    select_index,
    select_options,
    select_options as _ui_select_options,
    slider_range,
    slider_value,
    toggle_value,
    value_at_track,
)
from Application.Core.UI.layout import UIQuad, rect_hit, resolve_font
from Application.Core.UI.scene import collect_elements, find_by_name, find_by_role
from Application.Core.UI.theme import DEFAULT_TOKENS, resolve
from Application.Core.UI.tree import (
    EMPTY_RESULT,
    UIElement,
    UIBuildResult,
    build_ui,
    captures,
)

# 内置对话框里的两个按钮使用负 eid（不与场景实体冲突）
_BUILTIN_YES = -1
_BUILTIN_NO = -2


@dataclass
class _TextSpec:
    """`TextSystem.rasterize` 需要的字段子集（鸭子类型）。"""

    text: str = ""
    font: str = ""
    size: int = 28
    bold: bool = False
    italic: bool = False
    color: tuple = (1.0, 1.0, 1.0, 1.0)
    bg_color: tuple = (0.0, 0.0, 0.0, 0.0)
    align: str = "center"
    line_spacing: float = 1.15
    padding: int = 0
    wrap_width: int = 0


class RuntimeUILayer(Layer):
    """运行时 UI 层（模态对话框 + 叠加绘制）。"""

    # ── 状态（类属性 — OnAttach 复位）──
    _enabled: bool = True
    _open: bool = False          # 内置对话框是否打开
    _hover: str = ""             # 内置对话框悬停： "yes" | "no" | ""
    _pressed: str = ""           # 内置对话框按下： "yes" | "no" | ""
    _rects: dict = {}            # 内置对话框按钮矩形 name -> (x, y, w, h)
    _dirty: bool = True
    _mouse: tuple = (0.0, 0.0)
    _renderer = None

    # ── 场景 UI 状态 ──
    _elements: tuple = ()        # 逻辑线程写入的 UIElement 快照
    _exit_panel_eid: int = 0     # UIPanel(role="exit_confirm") 的实体 id（0 = 无）
    _overrides: dict = {}        # eid -> bool（运行期显隐；不改场景数据）
    _hover_eid: int = 0
    _pressed_eid: int = 0
    _scene_result: UIBuildResult = EMPTY_RESULT
    # ── 控件值（运行期状态，不写回 .scene）──
    _values: dict = {}           # eid -> bool/float/int
    _texts: dict = {}            # eid -> str（标签文本覆盖；`SetUIText` 写入）
    _expanded: int = 0           # 展开中的下拉选择 eid（0 = 无）
    _hover_index: int = -1       # segmented 悬停分段
    _press_kind: str = ""        # 按下时的控件类型（决定 release 行为）
    _drag_track: tuple = ()      # slider 拖拽轨道 (x0, x1)
    _events: deque = deque(maxlen=128)   # UI 事件队列（OnUIClick 节点消费）

    # 文案（内置对话框；宿主可注入 — 编辑器侧用 i18n）
    _title: str = "Exit game?"
    _yes: str = "Yes"
    _no: str = "No"
    _hint: str = "Esc / No = stay, Yes = exit"

    # 布局（参考分辨率像素）
    _PANEL_W: float = 620.0
    _PANEL_H: float = 300.0
    _BTN_W: float = 200.0
    _BTN_H: float = 64.0
    _BTN_GAP: float = 24.0

    _text_cache: dict = {}

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls) -> None:
        cls._renderer = getattr(cls._engine, "renderer", None)
        cls._open = False
        cls._hover = ""
        cls._pressed = ""
        cls._rects = {}
        cls._dirty = True
        cls._elements = ()
        cls._exit_panel_eid = 0
        cls._overrides = {}
        cls._hover_eid = 0
        cls._pressed_eid = 0
        cls._scene_result = EMPTY_RESULT
        cls._values = {}
        cls._texts = {}
        cls._expanded = 0
        cls._hover_index = -1
        cls._press_kind = ""
        cls._drag_track = ()
        cls._events = deque(maxlen=128)

    @classmethod
    def OnDetach(cls) -> None:
        cls._renderer = None
        cls._open = False
        cls._rects = {}
        cls._elements = ()
        cls._exit_panel_eid = 0
        cls._overrides = {}
        cls._hover_eid = 0
        cls._pressed_eid = 0
        cls._scene_result = EMPTY_RESULT
        cls._values = {}
        cls._texts = {}
        cls._expanded = 0
        cls._hover_index = -1
        cls._press_kind = ""
        cls._drag_track = ()
        cls._events = deque(maxlen=128)
        try:  # 清掉上一帧的 quad（渲染器可能已销毁 → 静默）
            renderer = getattr(cls._engine, "renderer", None)
            if renderer is not None:
                renderer.set_ui_quads(())
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def OnUpdate(cls) -> None:
        """逻辑线程：读 ECS → 不可变快照（渲染线程不碰 esper）。"""
        engine = cls._engine
        scene = getattr(engine, "scene", None) if engine is not None else None
        if scene is None:
            return
        try:
            cls._elements = collect_elements(scene)
        except Exception as e:  # noqa: BLE001 — UI 采集失败不应打断游戏循环
            cls._elements = ()
            print(f"[RuntimeUILayer] collect failed: {e!r}")
            return
        cls._exit_panel_eid = find_by_role(cls._elements, "exit_confirm")

    # ════════════════════════════════════════════════════════════
    # 配置（宿主 / 测试）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def configure(cls, title: str | None = None, yes: str | None = None,
                  no: str | None = None, hint: str | None = None) -> None:
        """注入文案（编辑器侧传当前语言的译文）。"""
        if title is not None:
            cls._title = str(title)
        if yes is not None:
            cls._yes = str(yes)
        if no is not None:
            cls._no = str(no)
        if hint is not None:
            cls._hint = str(hint)
        cls._dirty = True

    @classmethod
    def set_enabled(cls, enabled) -> None:
        cls._enabled = bool(enabled)
        if not cls._enabled:
            cls._close()

    @classmethod
    def is_open(cls) -> bool:
        """有任意确认界面开着（场景面板或内置对话框）。"""
        if cls._open:
            return True
        return bool(cls._exit_panel_eid) and cls.panel_visible(cls._exit_panel_eid)

    @classmethod
    def is_enabled(cls) -> bool:
        return bool(cls._enabled)

    @classmethod
    def open(cls) -> None:
        """打开退出确认（场景面板优先，否则内置对话框）。"""
        cls._hover = ""
        cls._pressed = ""
        cls._dirty = True
        if cls._exit_panel_eid:
            cls.panel_visible(cls._exit_panel_eid, True)
            return
        cls._open = True

    @classmethod
    def _close(cls) -> None:
        cls._open = False
        cls._hover = ""
        cls._pressed = ""
        cls._rects = {}
        cls._hover_eid = 0
        cls._pressed_eid = 0
        if cls._exit_panel_eid:
            cls.panel_visible(cls._exit_panel_eid, False)
        cls._dirty = True

    # ════════════════════════════════════════════════════════════
    # 场景面板显隐（运行期覆盖 — 不改场景数据）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def panel_visible(cls, eid: int, value=None) -> bool:
        """读/写一个 UI 元素的运行期可见性（value=None 只读）。"""
        eid = int(eid)
        if eid <= 0:
            return False
        if value is not None:
            cls._overrides[eid] = bool(value)
            if not value and eid in (cls._hover_eid, cls._pressed_eid):
                cls._hover_eid = 0
                cls._pressed_eid = 0
            cls._dirty = True
            return bool(value)
        override = cls._overrides.get(eid)
        if override is not None:
            return bool(override)
        for el in cls._elements:
            if int(el.eid) == eid:
                return bool(getattr(el.rect, "visible", True))
        return False

    @classmethod
    def captures_at(cls, x: float, y: float) -> bool:
        """屏幕像素坐标处是否应被 UI 捕获（overlay 穿透判定用）。"""
        if cls._open:
            return True
        return captures(cls._scene_result, x, y)

    # ════════════════════════════════════════════════════════════
    # 事件（模态消费）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        # ── ESC：先关；没开就开（关闭窗口的安全网交回引擎）──
        if isinstance(event, WindowCloseEvent):
            if getattr(event, "source", "window") != "escape":
                return
            if cls.is_open():
                cls._close()
                event.consume()
            elif cls._enabled:
                cls.open()
                event.consume()
            return

        # ── 内置对话框画在最上层 → 优先吃输入 ──
        if cls._open:
            if isinstance(event, MouseMoveEvent):
                cls._mouse = (float(event.pos_x), float(event.pos_y))
                cls._update_hover()
                event.consume()
                return
            if isinstance(event, MouseButtonEvent):
                if int(event.button) == 0:
                    cls._on_left_button(int(event.action),
                                        float(event.pos_x), float(event.pos_y))
                event.consume()
                return
            if isinstance(event, KeyboardButtonEvent):
                event.consume()
                return

        # ── 场景 UI ──
        if not cls._elements:
            return

        if isinstance(event, MouseMoveEvent):
            cls._mouse = (float(event.pos_x), float(event.pos_y))
            cls._update_scene_hover()
            if cls._pressed_eid and cls._drag_track:
                cls._drag_slider(float(event.pos_x))
            if cls._scene_modal():
                event.consume()
            return

        if isinstance(event, MouseButtonEvent):
            x, y = float(event.pos_x), float(event.pos_y)
            hit = cls._scene_hit(x, y)
            if int(event.button) != 0:
                if cls._scene_modal():
                    event.consume()
                return
            if int(event.action) == 1:          # press
                if hit is None:
                    cls._expanded = 0           # 点空白 → 收下拉
                cls._pressed_eid = int(hit.eid) if hit is not None else 0
                cls._press_kind = str(getattr(hit, "kind", "")) if hit is not None else ""
                cls._drag_track = (tuple(hit.track)
                                   if (hit is not None and hit.kind == "slider") else ())
                cls._dirty = True
                if hit is not None:
                    if hit.kind == "slider":
                        cls._drag_slider(x)          # 按下即跳到光标位置
                    elif hit.kind == "dropdown":
                        cls._expanded = 0 if cls._expanded == int(hit.eid) else int(hit.eid)
                    event.consume()
                elif cls._scene_modal():
                    event.consume()
                return
            # release
            activate = hit is not None and int(hit.eid) == cls._pressed_eid
            kind = cls._press_kind
            cls._pressed_eid = 0
            cls._press_kind = ""
            cls._drag_track = ()
            cls._dirty = True
            if hit is not None or cls._scene_modal():
                event.consume()
            if activate:
                cls._on_release(hit, kind)
            return

        if isinstance(event, KeyboardButtonEvent):
            if cls._scene_modal():
                event.consume()
            return

    @classmethod
    def _on_left_button(cls, action: int, x: float, y: float) -> None:
        # 0 = release, 1 = press（与 ImGui/GLFW 约定一致）
        hit = cls._hit(x, y)
        if action == 1:
            cls._pressed = hit
            cls._dirty = True
            return
        if action == 0:
            activate = hit and hit == cls._pressed
            cls._pressed = ""
            cls._dirty = True
            if activate:
                cls._activate(hit)

    @classmethod
    def _activate(cls, name: str) -> None:
        if name == "yes":
            cls._close()
            from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer
            RuntimeNodeLayer.request_stop()
        elif name == "no":
            cls._close()

    @classmethod
    def _hit(cls, x: float, y: float) -> str:
        for name, rect in cls._rects.items():
            if rect_hit(rect, x, y):
                return name
        return ""

    @classmethod
    def _update_hover(cls) -> None:
        new = cls._hit(*cls._mouse)
        if new != cls._hover:
            cls._hover = new
            cls._dirty = True

    # ── 场景 UI 交互 ──

    @classmethod
    def _scene_modal(cls) -> bool:
        return bool(getattr(cls._scene_result, "modal", False))

    @classmethod
    def _scene_hit(cls, x: float, y: float):
        result = cls._scene_result
        if result is None:
            return None
        return result.hit_at(x, y)

    @classmethod
    def _update_scene_hover(cls) -> None:
        hit = cls._scene_hit(*cls._mouse)
        new = int(hit.eid) if hit is not None else 0
        idx = int(getattr(hit, "index", 0)) if hit is not None else -1
        if new != cls._hover_eid or (hit is not None and idx != cls._hover_index):
            cls._hover_eid = new
            cls._hover_index = idx if new else -1
            cls._dirty = True

    # ── 控件值（运行期状态）──

    @classmethod
    def _element(cls, eid: int):
        for el in cls._elements:
            if int(el.eid) == int(eid):
                return el
        return None

    @classmethod
    def _resolve_eid(cls, target) -> int:
        """实体 id / 名字 → eid。

        名字先在 UI 元素快照里找，找不到再查场景实体表 —— 节点图的 `OnGameStart`
        可能早于第一帧 UI 快照（层顺序），所以不能只靠快照。
        """
        if isinstance(target, int):
            return max(0, int(target))
        text = str(target or "").strip()
        if not text:
            return 0
        if text.isdigit():
            return int(text)
        eid = int(find_by_name(cls._elements, text))
        if eid:
            return eid
        scene = getattr(cls._engine, "scene", None) if cls._engine is not None else None
        if scene is None:
            return 0
        try:
            return max(0, int(scene.GetEntityByName(text)))
        except Exception:  # noqa: BLE001 — 无该 API 的宿主
            return 0

    @classmethod
    def _drag_slider(cls, x: float) -> None:
        eid = int(cls._pressed_eid)
        el = cls._element(eid)
        if el is None or el.slider is None or not cls._drag_track:
            return
        lo, hi, step = slider_range(el.slider)
        cls._values[eid] = value_at_track(cls._drag_track, x, lo, hi, step)
        cls._dirty = True

    @classmethod
    def _on_release(cls, hit, kind: str) -> None:
        """鼠标释放：按控件类型更新值，再执行动作 + 发 UI 事件。"""
        eid = int(hit.eid)
        if kind in ("", "button"):
            cls._run_action(hit)
            cls._emit(eid, hit)      # 按钮也要发事件（OnUIClick 节点靠它）
            return

        el = cls._element(eid)
        if el is None:
            return
        if kind == "toggle" and el.toggle is not None:
            cls._values[eid] = not toggle_value(cls._values, eid, el.toggle)
        elif kind == "select" and el.select is not None:
            opts = select_options(el.select)
            idx = max(0, min(max(0, len(opts) - 1), int(hit.index)))
            cls._values[eid] = idx
            cls._expanded = 0
        elif kind == "step" and el.select is not None:
            opts = select_options(el.select)
            cur = select_index(cls._values, eid, el.select)
            total = max(1, len(opts))
            cls._values[eid] = max(0, min(total - 1, cur + int(hit.index)))
        elif kind == "dropdown":
            # 展开框本身在按下时已切换；这里不发事件
            return
        cls._dirty = True
        cls._run_action(hit)
        cls._emit(eid, hit)

    @classmethod
    def _emit(cls, eid: int, hit) -> None:
        """发一条 UI 事件（`OnUIClick` 节点消费）。

        记录用**对象**（与 `RuntimeInputFrame` 的 `.kind` 约定一致）；
        节点求值器统一 `getattr(event, "kind")` 读。
        """
        el = cls._element(eid)
        value, index = cls.read_value(eid)
        cls._events.append(SimpleNamespace(
            kind="ui_event",
            eid=int(eid),
            name=str(getattr(el, "name", "") or ""),
            action=str(getattr(hit, "action", "") or ""),
            control=str(getattr(hit, "kind", "") or ""),
            value=float(value),
            index=int(index),
        ))

    @classmethod
    def drain_events(cls) -> list:
        """逻辑线程：取走自上次以来的 UI 事件（节点图用）。"""
        out = list(cls._events)
        cls._events.clear()
        return out

    @classmethod
    def read_value(cls, target) -> tuple:
        """读控件当前值 → (value: float, index: int)；按钮/面板 → (1/0, 0)。"""
        eid = cls._resolve_eid(target)
        el = cls._element(eid)
        if el is None:
            return (0.0, 0)
        if el.toggle is not None:
            return (1.0 if toggle_value(cls._values, eid, el.toggle) else 0.0, 0)
        if el.slider is not None:
            return (float(slider_value(cls._values, eid, el.slider)), 0)
        if el.select is not None:
            idx = select_index(cls._values, eid, el.select)
            return (float(idx), idx)
        return (1.0 if cls.panel_visible(eid) else 0.0, 0)

    @classmethod
    def set_visible(cls, target, visible: bool) -> bool:
        """按实体 id / 名字设显隐（`SetUIVisible` 节点用）。"""
        eid = cls._resolve_eid(target)
        if not eid:
            return False
        cls.panel_visible(eid, bool(visible))
        return True

    @classmethod
    def set_text(cls, target, text) -> bool:
        """按实体 id / 名字设标签文本（`SetUIText` 节点用）。

        覆盖只存在于运行期（不写回 .scene / prefab）；传 None 或空串清空覆盖，
        回落到 `UILabel.text` 的静态内容。
        """
        eid = cls._resolve_eid(target)
        if not eid:
            return False
        value = "" if text is None else str(text)
        if value:
            cls._texts[eid] = value
        else:
            cls._texts.pop(eid, None)
        cls._dirty = True
        return True

    @classmethod
    def get_text(cls, target) -> str:
        """读标签当前文本（覆盖优先，其次 `UILabel.text`）。"""
        eid = cls._resolve_eid(target)
        if not eid:
            return ""
        if eid in cls._texts:
            return cls._texts[eid]
        el = cls._element(eid)
        return str(getattr(el.label, "text", "") or "") if el is not None and el.label is not None else ""

    @classmethod
    def _run_action(cls, hit) -> None:
        """执行按钮动作（`exit` / `close` / `show:名` / `hide:名` / `toggle:名`）。"""
        action = str(getattr(hit, "action", "") or "").strip()
        low = action.lower()
        if low in ("exit", "quit"):
            cls._close()
            from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer
            RuntimeNodeLayer.request_stop()
            return
        if low == "close":
            panel = int(getattr(hit, "panel_eid", 0) or 0)
            if panel:
                cls.panel_visible(panel, False)
            return
        for prefix, want in (("show:", True), ("hide:", False)):
            if low.startswith(prefix):
                eid = find_by_name(cls._elements, action[len(prefix):].strip())
                if eid:
                    cls.panel_visible(eid, want)
                return
        if low.startswith("toggle:"):
            eid = find_by_name(cls._elements, action[len("toggle:"):].strip())
            if eid:
                cls.panel_visible(eid, not cls.panel_visible(eid))
            return

    # ════════════════════════════════════════════════════════════
    # 绘制（渲染线程）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnRender(cls) -> None:
        renderer = cls._renderer or getattr(cls._engine, "renderer", None)
        if renderer is None:
            return
        has_scene_ui = bool(cls._elements)
        # 场景 UI 每帧重编（hover/press/override 都可能变）；文本有缓存 → 成本可忽
        if not cls._dirty and not has_scene_ui:
            return
        cls._dirty = False
        vw = int(getattr(renderer, "viewport_width", 0) or 0)
        vh = int(getattr(renderer, "viewport_height", 0) or 0)
        if vw <= 0 or vh <= 0:
            return

        # ★ 整体兜底: UI 编译/上传出问题不能打死渲染循环（宁可这帧没 UI）
        try:
            quads: list[UIQuad] = []
            if has_scene_ui:
                result = build_ui(
                    cls._elements, vw, vh,
                    hover_eid=cls._hover_eid, pressed_eid=cls._pressed_eid,
                    visible_overrides=cls._overrides,
                    values=cls._values,
                    texts=cls._texts,
                    expanded_eid=cls._expanded,
                    hover_index=cls._hover_index,
                    text_fn=cls._raster,
                )
                cls._scene_result = result
                quads.extend(result.quads)
            else:
                cls._scene_result = EMPTY_RESULT
            if cls._open:
                quads.extend(cls.build_quads(vw, vh))
            renderer.set_ui_quads(tuple(quads))
        except Exception as e:  # noqa: BLE001
            if not getattr(cls, "_render_error_reported", False):
                cls._render_error_reported = True
                import traceback
                print(f"[RuntimeUILayer] render failed (UI disabled for this frame): {e!r}")
                traceback.print_exc()

    # ── 布局 + 文本 ─────────────────────────────────────────

    @classmethod
    def _text_image(cls, text: str, size: int, color: tuple) -> tuple:
        """文本 → (w, h, rgba, key)；按内容缓存（同一帧内重复调用命中缓存）。"""
        key = f"{text}|{size}|{color}"
        cached = cls._text_cache.get(key)
        if cached is not None:
            return cached
        from Application.Core.Text import TextSystem

        spec = _TextSpec(text=text, font=resolve_font(text), size=int(size),
                         color=color, bg_color=(0.0, 0.0, 0.0, 0.0),
                         align="center", padding=0)
        arr = TextSystem.rasterize(spec)
        h, w = int(arr.shape[0]), int(arr.shape[1])
        entry = (w, h, arr, key)
        if len(cls._text_cache) > 128:      # 简易上限，防止无限增长
            cls._text_cache.clear()
        cls._text_cache[key] = entry
        return entry

    @classmethod
    def _raster(cls, text: str, size: int, color: tuple, bold: bool = False) -> tuple:
        """`tree.build_ui` 的文本回调（测试可替换 `_text_image` 影响它）。"""
        return cls._text_image(text, size, color)

    # ── 内置对话框 → 元素模型（与场景 UI 同一套编译器）──

    @classmethod
    def _builtin_elements(cls) -> tuple:
        """内置退出确认 → `UIElement`（负 eid；颜色/字号全部走主题 token）。"""
        t = DEFAULT_TOKENS
        panel_w, panel_h = cls._PANEL_W, cls._PANEL_H
        btn_w, btn_h, gap = cls._BTN_W, cls._BTN_H, cls._BTN_GAP
        # 面板中心 = 屏幕中心；下列偏移都相对屏幕中心（参考分辨率像素）
        title_dy = 74.0 - panel_h / 2.0
        hint_dy = 130.0 - panel_h / 2.0
        btn_dy = (panel_h - btn_h - 34.0) + btn_h / 2.0 - panel_h / 2.0   # 按钮中心
        btn_dx = gap / 2.0 + btn_w / 2.0

        def rect(pos_x, pos_y, w, h, order=0):
            return SimpleNamespace(anchor="center", pivot="center",
                                   pos_x=float(pos_x), pos_y=float(pos_y),
                                   width=float(w), height=float(h),
                                   visible=True, order=int(order))

        def label(text, size, color_token, pos_y, order):
            lbl = SimpleNamespace(text=str(text), size=float(size),
                                  color=str(color_token), align="center", bold=False)
            return lbl, rect(0.0, pos_y, panel_w, 48.0, order)

        hint_size = int(resolve("@font.size.body", t) * 0.72)
        title_lbl, title_rect = label(cls._title, resolve("@font.size.title", t),
                                      "@color.text", title_dy, 1)
        hint_lbl, hint_rect = label(cls._hint, hint_size, "@color.text.muted", hint_dy, 2)

        return (
            # 遮罩（撑满视口：width/height = 0）
            UIElement(eid=-100, parent_id=None, canvas=None,
                      rect=rect(0.0, 0.0, 0.0, 0.0, 0),
                      panel=SimpleNamespace(bg_color="", border_width=0.0,
                                            scrim_color="@color.scrim",
                                            modal=True, role="exit_confirm_builtin")),
            # 面板底板
            UIElement(eid=-101, parent_id=None, canvas=None,
                      rect=rect(0.0, 0.0, panel_w, panel_h, 1),
                      panel=SimpleNamespace(bg_color="@color.surface",
                                            border_color="@color.border",
                                            border_width=1.0, scrim_color="",
                                            modal=False, role="")),
            UIElement(eid=-102, parent_id=None, canvas=None, rect=title_rect, label=title_lbl),
            UIElement(eid=-103, parent_id=None, canvas=None, rect=hint_rect, label=hint_lbl),
            UIElement(eid=_BUILTIN_NO, parent_id=None, canvas=None,
                      rect=rect(-btn_dx, btn_dy, btn_w, btn_h, 2),
                      button=SimpleNamespace(text=cls._no, variant="secondary",
                                             action="", enabled=True, size=0.0)),
            UIElement(eid=_BUILTIN_YES, parent_id=None, canvas=None,
                      rect=rect(btn_dx, btn_dy, btn_w, btn_h, 2),
                      button=SimpleNamespace(text=cls._yes, variant="primary",
                                             action="", enabled=True, size=0.0)),
        )

    @classmethod
    def build_quads(cls, viewport_w: int, viewport_h: int) -> tuple:
        """内置对话框 → quad 序列（同时刷新 `_rects` 供命中使用）。"""
        result = build_ui(
            cls._builtin_elements(), viewport_w, viewport_h,
            hover_eid=_BUILTIN_YES if cls._hover == "yes" else (
                _BUILTIN_NO if cls._hover == "no" else 0),
            pressed_eid=_BUILTIN_YES if cls._pressed == "yes" else (
                _BUILTIN_NO if cls._pressed == "no" else 0),
            text_fn=cls._raster,
        )
        rects = {}
        for hit in result.hits:
            if int(hit.eid) == _BUILTIN_YES:
                rects["yes"] = tuple(hit.rect)
            elif int(hit.eid) == _BUILTIN_NO:
                rects["no"] = tuple(hit.rect)
        cls._rects = rects
        return tuple(result.quads)


__all__ = ["RuntimeUILayer"]
