"""输入节点 widget — OnKeyPressed / OnKeyReleased / OnMouseClicked /
IsKeyDown / IsMouseButtonDown。"""

from __future__ import annotations

from imgui_bundle import imgui

from Application.Editor.I18n import t
from Application.Core.Input.InputBinding import (
    resolve_key_name,
    resolve_mod_name,
    resolve_mouse_button_name,
)
from .core import register, _ne_combo


_KEY_OPTIONS: list[str] = (
    ["Escape", "Space", "Enter", "Tab", "Backspace", "Delete",
     "Left", "Right", "Up", "Down", "Home", "End", "PageUp", "PageDown",
     "LeftShift", "RightShift", "LeftControl", "RightControl",
     "LeftAlt", "RightAlt"]
    + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(i) for i in range(10)]
    + [f"F{i}" for i in range(1, 13)]
)

_MOD_OPTIONS: list[tuple[str, str]] = [
    ("Any", "any"),
    ("None", "none"),
    ("Shift", "Shift"),
    ("Ctrl", "Ctrl"),
    ("Alt", "Alt"),
    ("Ctrl+Shift", "Ctrl+Shift"),
    ("Ctrl+Alt", "Ctrl+Alt"),
    ("Shift+Alt", "Shift+Alt"),
    ("Ctrl+Shift+Alt", "Ctrl+Shift+Alt"),
]

_BUTTON_OPTIONS: list[str] = ["Left", "Right", "Middle", "Any"]


def _key_index(name: str) -> int:
    try:
        return _KEY_OPTIONS.index(name)
    except ValueError:
        return 0


def _mod_index(name: str) -> int:
    for i, (_label, key) in enumerate(_MOD_OPTIONS):
        if key == name:
            return i
    return 0


def _button_index(name: str) -> int:
    if str(name).lower() == "any":
        return _BUTTON_OPTIONS.index("Any")
    try:
        return _BUTTON_OPTIONS.index(name)
    except ValueError:
        return 0


def _draw_key_combo(nid: int, inst, tag: str) -> None:
    current = resolve_key_name(inst.props.get("key", "Space"))
    labels = _KEY_OPTIONS
    changed, idx = _ne_combo(t("widget.input.key") + f"##{tag}_{nid}",
                             _key_index(current), labels)
    if changed:
        inst.props["key"] = labels[idx]


def _draw_mod_combo(nid: int, inst, tag: str) -> None:
    current = resolve_mod_name(inst.props.get("mods", "any"))
    labels = [label for label, _key in _MOD_OPTIONS]
    changed, idx = _ne_combo(t("widget.input.mods") + f"##{tag}_{nid}",
                             _mod_index(current), labels)
    if changed:
        inst.props["mods"] = _MOD_OPTIONS[idx][1]


@register("OnKeyPressed")
def _draw_on_key_pressed(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    _draw_key_combo(nid, inst, "okp_key")
    _draw_mod_combo(nid, inst, "okp_mods")
    repeat = bool(inst.props.get("repeat", False))
    changed, repeat = imgui.checkbox(t("widget.input.repeat") + f"##okp_rep_{nid}", repeat)
    if changed:
        inst.props["repeat"] = bool(repeat)
    imgui.pop_item_width()


@register("OnKeyReleased")
def _draw_on_key_released(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    _draw_key_combo(nid, inst, "okr_key")
    _draw_mod_combo(nid, inst, "okr_mods")
    imgui.pop_item_width()


@register("OnMouseClicked")
def _draw_on_mouse_clicked(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    current = resolve_mouse_button_name(inst.props.get("button", "Left"))
    changed, idx = _ne_combo(t("widget.input.button") + f"##omc_btn_{nid}",
                             _button_index(current), _BUTTON_OPTIONS)
    if changed:
        inst.props["button"] = _BUTTON_OPTIONS[idx]
    _draw_mod_combo(nid, inst, "omc_mods")
    imgui.pop_item_width()


@register("IsKeyDown")
def _draw_is_key_down(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    _draw_key_combo(nid, inst, "ikd_key")
    imgui.pop_item_width()


@register("IsMouseButtonDown")
def _draw_is_mouse_button_down(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    current = resolve_mouse_button_name(inst.props.get("button", "Left"))
    changed, idx = _ne_combo(t("widget.input.button") + f"##imbd_btn_{nid}",
                             _button_index(current), _BUTTON_OPTIONS)
    if changed:
        inst.props["button"] = _BUTTON_OPTIONS[idx]
    imgui.pop_item_width()
