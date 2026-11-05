"""UI 节点 —— 让节点图驱动运行期 UI（协议：`Doc/Dev/runtime_ui_protocol.md` §5）。

四个节点:
  - `SetUIVisible`  显示/隐藏一个 UI 实体（面板/控件；子元素随父级一起显隐）
  - `SetUIText`     改一个 `UILabel` 的文本（运行期覆盖，不改场景）
  - `OnUIClick`     按钮/开关/滑条/选择被操作时触发（图入口，按 `action`/`name` 过滤）
  - `GetUIValue`    读取控件当前值（开关 0/1、滑条数值、选择下标）

设计口径:
  - 目标既可以**连线**（`Entity` ← `EntityGet`），也可以**写名字**（props.target）——
    设置页/HUD 通常直接写面板名，少连一根线；
  - UI 状态存在 `RuntimeUILayer`（运行期覆盖），**不写回 `.scene`**；
  - `OnUIClick` 的事件由 `RuntimeNodeLayer` 在逻辑线程 drain 后触发（与键鼠事件同一条派发路径）。
"""

from . import _reg, _gen_id, UI_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "SetUIVisible", "Set UI Visible", "UI", UI_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref", optional=True),
        PinDef(_gen_id(), "Visible", "data", "input", "bool", optional=True),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Show/hide a UI element or panel by entity (props: target name, visible)",
))

_reg(NodeTypeDef(
    "SetUIText", "Set UI Text", "UI", UI_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref", optional=True),
        PinDef(_gen_id(), "Text", "data", "input", "string", optional=True),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Set a label's text at runtime (props: target name, text)",
))

_reg(NodeTypeDef(
    "OnUIClick", "On UI Click", "Event", UI_COLOR,
    [
        PinDef(_gen_id(), "exec", "exec", "output"),
        PinDef(_gen_id(), "Action", "data", "output", "string"),
        PinDef(_gen_id(), "Name", "data", "output", "string"),
        PinDef(_gen_id(), "Value", "data", "output", "float"),
        PinDef(_gen_id(), "Index", "data", "output", "int"),
    ],
    "Fires when a UI button/toggle/slider/select is used (props: action filter, name filter)",
))

_reg(NodeTypeDef(
    "GetUIValue", "Get UI Value", "UI", UI_COLOR,
    [
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref", optional=True),
        PinDef(_gen_id(), "Value", "data", "output", "float"),
        PinDef(_gen_id(), "Index", "data", "output", "int"),
    ],
    "Read a UI control's current value (props: target name)",
))
