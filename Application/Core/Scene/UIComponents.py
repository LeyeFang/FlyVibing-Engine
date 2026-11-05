"""运行时 UI 组件 — 场景驱动 UI 的数据契约（协议：`Doc/Dev/product_todo.md` §10）。

设计口径（2026-11-04 已定）:
  - **组合而非单组件**：`UIRect` 负责布局，`UIPanel/UILabel/UIButton` 负责外观与交互；
    带 UI 组件的实体由运行期 UI 层统一编译成绘制指令（**不绑 MeshRenderer**）。
  - **不入实体渲染通道**：UI 组件不产生世界空间网格，`MeshRenderer` 缺失即不进实体 pass。
  - **父子 = 实体父子**：子元素的位置相对于父元素的 `UIRect` 矩形（D9）；
    无 `UIPanel/UILabel/UIButton` 的父实体（如纯容器）仍然参与布局链。
  - **颜色/字号写 token**（`@color.surface`），不写死 RGB —— 主题见 `Core/UI/theme.py`。
  - **交互只由按钮产生**：面板/文字不抢点击（overlay 穿透语义：没画按钮的地方可穿）。

坐标：`UIRect` 的 `pos/size` 都写在**参考分辨率**（`UICanvas.reference_w/h`）里，
由 `Core/UI/layout.content_box` 统一缩放到视口。

典型树（一个退出确认对话框）:

    ExitDialog (UICanvas + UIRect + UIPanel role="exit_confirm" modal=True visible=False)
      ├ Title   (UIRect + UILabel)
      ├ Hint    (UIRect + UILabel)
      ├ Stay    (UIRect + UIButton action="close")
      └ Quit    (UIRect + UIButton variant="primary" action="exit")
"""

from __future__ import annotations

from dataclasses import dataclass as component

from Application.Core.Scene.DataContract import DataclassContract, register_contract

# ── 受控枚举（Inspector 渲染下拉；值必须真实被运行期实现）──────────
ANCHORS: tuple[str, ...] = (
    "top_left", "top", "top_right",
    "left", "center", "right",
    "bottom_left", "bottom", "bottom_right",
)
SCALE_MODES: tuple[str, ...] = ("fit_height", "fit_width", "contain", "stretch")
ALIGNS: tuple[str, ...] = ("left", "center", "right")
BUTTON_VARIANTS: tuple[str, ...] = ("primary", "secondary", "danger", "ghost")
SELECT_SKINS: tuple[str, ...] = ("segmented", "stepper", "dropdown")


@component
class UICanvas(DataclassContract):
    """UI 画布 — 屏幕空间根（参考分辨率 + 缩放策略 + 排序）。

    - `scale_mode`: fit_height（默认，超宽屏两侧留边）/ fit_width / contain（宽高都贴合）
      / stretch（拉伸变形，谨慎）
    - `sort_order`: 多画布时的绘制顺序（小的先画 = 在下面）
    - 画布本身可同时带 `UIRect + UIPanel`（当全屏根面板用）
    """

    scale_mode: str = "fit_height"
    reference_w: int = 1920
    reference_h: int = 1080
    sort_order: int = 0
    visible: bool = True


@component
class UIRect(DataclassContract):
    """UI 矩形 — 相对父元素（或画布内容框）的 9 宫格锚点布局。

    - `anchor`: 相对**父矩形**的锚点（无父元素 → 画布内容框）
    - `pivot`: 矩形自身对齐点（默认与 anchor 相同 → 贴角/居中）
    - `pos_x / pos_y`: 锚点处的偏移（参考分辨率像素）
    - `width / height`: 参考分辨率像素（0 = 沿用该轴父尺寸，便于做"撑满"）
    - `visible`: 自身可见性（父不可见 → 子树整体不画、不命中）
    - `order`: 同层绘制顺序（小的先画 = 在下面；同值按实体创建顺序）
    """

    anchor: str = "center"
    pivot: str = "center"
    pos_x: float = 0.0
    pos_y: float = 0.0
    width: float = 320.0
    height: float = 120.0
    visible: bool = True
    order: int = 0


@component
class UIPanel(DataclassContract):
    """面板 / 浮窗 / 对话框底板。

    - `bg_color` / `border_color`: token 名（`@color.surface`）或 RGBA tuple
    - `border_width`: 0 = 无描边（M0 直角；圆角后置）
    - `scrim_color`: 非空 → 整屏遮罩（对话框用 `@color.scrim`）
    - `modal`: 吃掉全部键鼠（节点图收不到）；关闭后事件恢复
    - `role`: 语义标记 — `"exit_confirm"` 表示 ESC 退出确认面板（引擎按此找面板）
    """

    bg_color: str = "@color.surface"
    border_color: str = "@color.border"
    border_width: float = 1.0
    scrim_color: str = ""
    modal: bool = False
    role: str = ""


@component
class UILabel(DataclassContract):
    """不可编辑文字（多行 = 同一控件 + 手动换行符；自动折行后置）。

    - `size`: 0 = 主题 `@font.size.body`；>0 = 参考分辨率像素
    - `color`: token 名或 RGBA
    - `align`: left / center / right（垂直始终居中）
    """

    text: str = "Label"
    size: float = 0.0
    color: str = "@color.text"
    align: str = "center"
    bold: bool = False


@component
class UIButton(DataclassContract):
    """按钮 — 唯一产生点击的元素；文字画在按钮内（不要再挂 UILabel 子实体）。

    - `variant`: primary / secondary / danger / ghost（语义色，颜色由主题决定）
    - `action`: 点击动作 —
        `""`        仅视觉（不消费点击）
        `exit`      请求停止（PIE → SimulationController.stop；与 ExitGame 节点同链）
        `close`     关闭所属面板（最近一层带 UIPanel 的父元素）
        `show:名字` / `hide:名字` / `toggle:名字`  按实体名显隐面板
    - `enabled`: False → 变灰且不可点
    """

    text: str = "Button"
    variant: str = "secondary"
    action: str = ""
    enabled: bool = True
    size: float = 0.0


# ═══════════════════════════════════════════════════════════════
# 设置页三件套（开关 / 滑条 / 离散选择）
# ═══════════════════════════════════════════════════════════════
# 共同点:
#   - `label` 非空 → 左侧留出说明文字区（百分比见 `Core/UI/tree.py` 的 `LABEL_RATIO`）
#   - `action` 与 `UIButton` 同语义；变化时作为一次 UI 事件派发（`OnUIClick` 节点可收）
#   - 值是**运行期状态**：存在 `RuntimeUILayer._values`（不写回 `.scene`），
#     节点用 `GetUIValue` 读；PIE 停止即丢弃（不会污染正在编辑的场景）

@component
class UIToggle(DataclassContract):
    """开关（布尔）。

    - `value`: 当前状态（点击翻转）
    - `label`: 左侧说明文字（可空）
    """

    label: str = ""
    value: bool = False
    action: str = ""
    size: float = 0.0


@component
class UISlider(DataclassContract):
    """连续/离散滑条。

    - `min_value` / `max_value`: 取值范围
    - `step`: 0 = 连续；>0 = 按步长吸附
    - `value`: 当前值
    - `show_value`: 右侧是否显示数值文本
    """

    label: str = ""
    min_value: float = 0.0
    max_value: float = 1.0
    step: float = 0.0
    value: float = 0.0
    show_value: bool = True
    action: str = ""
    size: float = 0.0


@component
class UISelect(DataclassContract):
    """离散档位选择 —— **一个数据模型，三种皮肤**（已定 2026-11-04）。

    - `options`: 选项文本（tuple/list 均可；`.scene` 里是 JSON 数组）
    - `index`: 当前选中下标（越界自动钳制）
    - `skin`: `segmented`（并排分段，2-4 项）/
              `stepper`（`−` 数值 `+`，多项或数值步进）/
              `dropdown`（点开列表，多项）
    """

    label: str = ""
    options: tuple = ()
    index: int = 0
    skin: str = "segmented"
    action: str = ""
    size: float = 0.0


# ── 注册到 Serializable 注册表（.scene 读写）────────────────────
register_contract("UICanvas", UICanvas)
register_contract("UIRect", UIRect)
register_contract("UIPanel", UIPanel)
register_contract("UILabel", UILabel)
register_contract("UIButton", UIButton)
register_contract("UIToggle", UIToggle)
register_contract("UISlider", UISlider)
register_contract("UISelect", UISelect)

# 组件名 → 类（ComponentRegistry.ensure_defaults 与测试共用一份清单）
UI_COMPONENTS: dict[str, type] = {
    "UICanvas": UICanvas,
    "UIRect": UIRect,
    "UIPanel": UIPanel,
    "UILabel": UILabel,
    "UIButton": UIButton,
    "UIToggle": UIToggle,
    "UISlider": UISlider,
    "UISelect": UISelect,
}


__all__ = [
    "UICanvas", "UIRect", "UIPanel", "UILabel", "UIButton",
    "UIToggle", "UISlider", "UISelect",
    "UI_COMPONENTS", "ANCHORS", "SCALE_MODES", "ALIGNS", "BUTTON_VARIANTS",
    "SELECT_SKINS",
]
