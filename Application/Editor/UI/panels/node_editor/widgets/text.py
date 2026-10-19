"""文字节点 widget — SetText (上游文本回显 + 组件提示)。"""

from __future__ import annotations

from imgui_bundle import imgui
from Application.Editor.I18n import t
from .core import register


@register("SetText")
def _draw_set_text_widgets(nid: int, inst, _canvas) -> None:
    """SetText — Text 由连线输入; 样式属于目标实体的 TextDisplay 组件。"""
    imgui.text_disabled(t("widget.text.from_pin"))
    imgui.text_disabled(t("widget.text.style_hint"))
