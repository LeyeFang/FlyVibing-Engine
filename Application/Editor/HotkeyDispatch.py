"""热键匹配与派发（ImGui 侧）— Core 注册表不含 imgui，导出成品不带 UI 工具包。

`Application/Core/Input/Hotkeys.py` 只做数据（注册/解析/排序/快照），
真正的按键判定在这里：`poll()` 每帧派发 `dispatch="global"` 的绑定，
拥有者（节点编辑器等）用 `fired(id)` 在自己语境里询问。
"""

from __future__ import annotations

from Application.Core.Input.Hotkeys import (Hotkey, get, is_dispatchable,
                                            parse_chord, resolve_key_name)


def _io():
    """当前 ImGui IO（无上下文/无 imgui → None）。"""
    try:
        from imgui_bundle import imgui

        if imgui.get_current_context() is None:
            return None
        return imgui.get_io()
    except Exception:  # noqa: BLE001 — 无头/未初始化
        return None


def _key_code(name: str):
    """和弦键名 → `imgui.Key`。"""
    from imgui_bundle import imgui

    alias = resolve_key_name(name)
    code = getattr(imgui.Key, alias, None)
    if code is None:
        raise ValueError(f"unknown key name {name!r} (imgui.Key.{alias} missing)")
    return code


def _mods_match(io, mods: tuple[str, ...]) -> bool:
    """修饰键必须**完全一致**（按 G 时按着 Ctrl 不算）。"""
    return (bool(io.key_ctrl) == ("ctrl" in mods)
            and bool(io.key_shift) == ("shift" in mods)
            and bool(io.key_alt) == ("alt" in mods)
            and bool(io.key_super) == ("super" in mods))


def _editable_focus(io) -> bool:
    """焦点在输入框/文本框里 → 热键让路（不抢按键）。"""
    return bool(getattr(io, "want_capture_keyboard", False)
                or getattr(io, "want_text_input", False))


def fired(hotkey_id: str) -> bool:
    """本帧是否按下了这条热键（边沿触发；文本框聚焦时恒 False）。"""
    hk = get(hotkey_id)
    if hk is None or hk.kind != "key":
        return False
    io = _io()
    if io is None or _editable_focus(io):
        return False
    from imgui_bundle import imgui

    key, mods = parse_chord(hk.keys)
    if not _mods_match(io, mods):
        return False
    try:
        return bool(imgui.is_key_pressed(_key_code(key), False))
    except ValueError:
        return False


def down(hotkey_id: str) -> bool:
    """这条热键的键位当前是否按住（文本框聚焦时恒 False）。"""
    hk = get(hotkey_id)
    if hk is None or hk.kind != "key":
        return False
    io = _io()
    if io is None or _editable_focus(io):
        return False
    from imgui_bundle import imgui

    key, mods = parse_chord(hk.keys)
    if not _mods_match(io, mods):
        return False
    try:
        return bool(imgui.is_key_down(_key_code(key)))
    except ValueError:
        return False


def poll() -> int:
    """每帧调用：派发所有 `dispatch="global"` 的热键。返回本轮触发条数。"""
    fired_count = 0
    for hk in list(_all()):
        if not is_dispatchable(hk):
            continue
        if not fired(hk.id):
            continue
        fired_count += 1
        try:
            hk.impl()
        except Exception as exc:  # noqa: BLE001 — 一个动作失败不影响其它热键
            print(f"[Hotkeys] {hk.id} failed: {exc!r}")
    return fired_count


def _all() -> list[Hotkey]:
    from Application.Core.Input.Hotkeys import all_hotkeys
    return all_hotkeys()
