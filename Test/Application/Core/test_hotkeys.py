"""热键注册表守卫（core，无窗口）。

背景（2026-11-04，用户反馈"input 对 agent 和人的提示不够"）:
  热键以前散在 EditorInputLayer（G/R/S/Space）、节点编辑器（Delete）、窗口（Esc），
  主菜单还写着没实现的 Ctrl+N/S/Z。人和 agent 都无法判断"按这个键到底会怎样"。

本测试锁定:
  1. 和弦解析/规范化 + 非法输入报错
  2. 注册约束: 重复 id / 同 scope 重复和弦 / global 无 impl / 未知 scope·kind·dispatch
  3. 生产注册表: 每条都有 `hotkey.<id>` 中英词条、global 必带 impl、scope 合法
  4. CLI/面板/服务器三方同源: `hotkeys.list` 在 ops 表与 LiveCommandServer 都有
  5. 无漂移: EditorInputLayer 不再硬编码 G/R/S 键位
"""

# TIER: core

from __future__ import annotations

import json
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

_ROOT = _d
while _ROOT and not os.path.exists(os.path.join(_ROOT, "startup.bat")):
    _parent = os.path.dirname(_ROOT)
    if _parent == _ROOT:
        _ROOT = ""
        break
    _ROOT = _parent

import Application.Core.Input.Hotkeys as HK  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    except Exception:  # noqa: BLE001 — 其它异常同样算失败
        return False
    return False


def main() -> int:
    print("=" * 60)
    print("hotkey registry — chord parsing / registration rules / 3-way sync")
    print("=" * 60)

    # ── 1. 和弦解析 ──
    print("-- 1. chord parsing --")
    check("normalize(ctrl+shift+s) = Ctrl+Shift+S",
          HK.normalize("ctrl+shift+s") == "Ctrl+Shift+S", HK.normalize("ctrl+shift+s"))
    check("normalize(g) = G", HK.normalize("g") == "G")
    check("normalize(esc) = Escape", HK.normalize("esc") == "Escape")
    check("parse_chord 修饰键顺序规范化",
          HK.parse_chord("Shift+Ctrl+S") == ("s", ("ctrl", "shift")),
          str(HK.parse_chord("Shift+Ctrl+S")))
    check("空和弦报错", _raises(lambda: HK.parse_chord("")))
    check("未知修饰键报错", _raises(lambda: HK.parse_chord("Hyper+G")))

    # ── 2. 注册约束（沙箱）──
    print("-- 2. registration rules (sandbox) --")
    saved = dict(HK._REGISTRY)
    saved_chords = dict(HK._CHORDS)
    try:
        HK.clear()
        HK.register(HK.Hotkey(id="t.a", keys="g", scope="viewport", action="a",
                              description_key="hotkey.t.a"))
        check("合法注册后出现在 all_hotkeys", [h.id for h in HK.all_hotkeys()] == ["t.a"])
        check("重复 id 报错", _raises(lambda: HK.register(HK.Hotkey(
            id="t.a", keys="h", scope="viewport", action="a", description_key="hotkey.t.a"))))
        check("同 scope 重复和弦报错", _raises(lambda: HK.register(HK.Hotkey(
            id="t.b", keys="G", scope="viewport", action="b", description_key="hotkey.t.b"))))
        HK.register(HK.Hotkey(id="t.c", keys="G", scope="node_editor", action="c",
                              description_key="hotkey.t.c"))
        check("跨 scope 同和弦允许", HK.get("t.c") is not None)
        check("未知 scope 报错", _raises(lambda: HK.register(HK.Hotkey(
            id="t.d", keys="k", scope="nowhere", action="d", description_key="hotkey.t.d"))))
        check("未知 kind 报错", _raises(lambda: HK.register(HK.Hotkey(
            id="t.e", keys="k", scope="viewport", action="e",
            description_key="hotkey.t.e", kind="gesture"))))
        check("global 缺 impl 报错", _raises(lambda: HK.register(HK.Hotkey(
            id="t.f", keys="k", scope="viewport", action="f",
            description_key="hotkey.t.f", dispatch="global"))))
        check("global 带 impl 可注册", HK.register(HK.Hotkey(
            id="t.g", keys="k", scope="viewport", action="g",
            description_key="hotkey.t.g", dispatch="global",
            impl=lambda: None)).keys == "K")
        mouse = HK.register(HK.Hotkey(id="t.m", keys="MMB drag", scope="viewport",
                                      action="m", description_key="hotkey.t.m",
                                      kind="mouse"))
        check("mouse 提示保留原文键位", mouse.keys == "MMB drag", mouse.keys)
        snap = HK.snapshot(lambda k, fb: f"d:{k}")
        check("snapshot 带解析后的说明与 scope",
              snap and snap[0]["description"].startswith("d:hotkey.")
              and {"id", "scope", "keys", "action", "kind", "dispatch"} <= set(snap[0]),
              str(snap[0]))
        check("snapshot 键盘绑定排在鼠标提示前",
              [r["kind"] for r in snap][:1] == ["key"], str([r["kind"] for r in snap]))
        check("scope 过滤生效",
              all(r["scope"] == "node_editor" for r in HK.snapshot(None, scope="node_editor")))
    finally:
        HK._REGISTRY.clear()
        HK._REGISTRY.update(saved)
        HK._CHORDS.clear()
        HK._CHORDS.update(saved_chords)

    # ── 3. 生产注册表 ──
    print("-- 3. production registry --")
    from Application.Editor.HotkeyActions import register_editor_hotkeys
    register_editor_hotkeys()
    rows = HK.all_hotkeys()
    check("注册表非空", len(rows) >= 8, f"{len(rows)} entries")
    check("scope 全部合法", all(h.scope in HK.SCOPES for h in rows),
          str([h.scope for h in rows if h.scope not in HK.SCOPES]))
    check("global 条目都有 impl",
          all(h.impl is not None for h in rows if h.dispatch == "global"))
    check("description_key 约定 = hotkey.<id>",
          all(h.description_key == f"hotkey.{h.id}" for h in rows),
          str([h.id for h in rows if h.description_key != f"hotkey.{h.id}"]))
    check("key 条目都能解析成和弦",
          all(_raises(lambda k=h.keys: HK.parse_chord(k)) is False
              for h in rows if h.kind == "key"))

    # 词条: en + zh 都在且非空
    locale_dir = os.path.join(_ROOT, "Application", "Editor", "Locale")
    missing: list[str] = []
    for lang in ("en", "zh"):
        with open(os.path.join(locale_dir, f"{lang}.json"), encoding="utf-8-sig") as fh:
            strings = json.load(fh)["strings"]
        missing += [f"{lang}:{h.description_key}" for h in rows
                    if not strings.get(h.description_key)]
    check("每条热键都有 en/zh 文案", not missing, str(missing[:4]))

    # ── 4. 三方同源（面板 / CLI / 服务器）──
    print("-- 4. CLI + panel sync --")
    from engine_editor_mcp import ops as op_registry
    check("ops 表含 hotkeys.list", "hotkeys.list" in op_registry.OPS)
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer
    check("LiveCommandServer 实现 hotkeys.list",
          hasattr(LiveCommandServer, "_op_hotkeys_list"))
    from Application.Editor.UI.panels.HotkeysPanel import HotkeysPanel
    panel_rows = HotkeysPanel._rows()
    check("面板数据 = 注册表（同一来源、同样条数）",
          [r["id"] for r in panel_rows] == [h.id for h in rows],
          f"{len(panel_rows)} vs {len(rows)}")
    check("面板文案已本地化（拿到的是译文而非 key）",
          all(not r["description"].startswith("hotkey.") for r in panel_rows),
          str([r["description"] for r in panel_rows[:2]]))

    # ── 5. 无漂移: 编辑器输入层不再硬编码键位 ──
    print("-- 5. no hard-coded keys left --")
    src = os.path.join(_ROOT, "Application", "Editor", "EditorInputLayer.py")
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    check("EditorInputLayer 不再引用 KeyButtonCode.G/R/S",
          all(tok not in text for tok in ("KeyButtonCode.G", "KeyButtonCode.R",
                                          "KeyButtonCode.S", "KeyButtonCode.Space")))

    # Core 注册表必须与 UI 工具包解耦（导出成品不带 imgui）
    import re as _re

    core_src = os.path.join(_ROOT, "Application", "Core", "Input", "Hotkeys.py")
    with open(core_src, encoding="utf-8") as fh:
        core_text = fh.read()
    has_imgui_import = bool(_re.search(r"(?m)^\s*(?:from|import)\s+imgui_bundle", core_text))
    check("Core/Input/Hotkeys.py 不 import imgui（成品不带 UI 工具包）",
          not has_imgui_import)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
