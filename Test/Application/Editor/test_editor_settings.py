"""
设置体系 — EditorSettings / I18n / SettingsPanel 页面注册表 / settings.* ops (无头)。

协议: Doc/Dev/ui_protocol.md §13 (Settings 面板与设置体系)。
锁定内容:
  1. EditorSettings: 默认值 / 落盘往返 / clamp / 枚举回退 / 未知键 KeyError / 损坏 JSON 容错
  2. pending 应用模型: set 只入队 -> apply_pending (渲染线程帧首) 出队并调 hook, 只应用一次
  3. I18n: 命中 / 缺键回退键名 / set_language 非法 -> en
  4. SettingsPanel 页面注册表: 内置两页同级 / 重名 ValueError / owner 清理 / 排序
  5. settings.get / settings.set op 与面板同一业务单点 (Action 契约: 动作单点)

运行: python Utils/Dev/test_runner.py --only editor_settings
"""
# TIER: core

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)  # repo root
_ROOT = _d

# ── 沙箱: 设置文件指向临时目录 (必须先于任何 load/set) ──
_TMP = tempfile.mkdtemp(prefix="mge_settings_")
os.environ["MGE_EDITOR_SETTINGS"] = os.path.join(_TMP, "settings.json")

from Application.Editor.EditorSettings import DEFAULTS, EditorSettings          # noqa: E402
from Application.Editor.I18n import get_language, set_language, t               # noqa: E402
from Application.Editor.StartupOptions import parse_args                         # noqa: E402
from Application.Editor.Services.LiveCommandServer import LiveCommandServer     # noqa: E402
from Application.Editor.UI.panels.SettingsPanel import SettingsPage, SettingsPanel  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _rm_settings_file() -> None:
    try:
        os.remove(EditorSettings.path())
    except OSError:
        pass


def main() -> int:
    print("=" * 60)
    print("Editor settings — service / pending model / i18n / page registry / ops")
    print("=" * 60)

    # ═══════════════════════════════════════════════════════════
    # 1. 服务基础: 默认值 / 沙箱
    # ═══════════════════════════════════════════════════════════
    print("-- 1. defaults + sandbox --")
    EditorSettings._reset_for_tests()
    _rm_settings_file()
    EditorSettings.load()
    check("默认值 (font_scale=1.0 / language=en / port=8977)",
          EditorSettings.get("ui.font_scale") == 1.0 and EditorSettings.get("ui.language") == "en"
          and EditorSettings.get("server.port") == 8977,
          f"{EditorSettings.get('ui.font_scale')!r} {EditorSettings.get('ui.language')!r} "
          f"{EditorSettings.get('server.port')!r}")
    check("all() 覆盖 DEFAULTS 全部键", set(EditorSettings.all()) == set(DEFAULTS))
    check("MGE_EDITOR_SETTINGS 沙箱生效", EditorSettings.path().startswith(_TMP), EditorSettings.path())

    # ═══════════════════════════════════════════════════════════
    # 2. 写入: 定格值 / 立即落盘 / clamp / 枚举 / 未知键
    # ═══════════════════════════════════════════════════════════
    print("-- 2. set: coerce + persist --")
    check("set 返回定格值", EditorSettings.set("ui.font_scale", 1.25) == 1.25)
    with open(EditorSettings.path(), encoding="utf-8") as fh:
        on_disk = json.load(fh)
    check("set 立即落盘", on_disk.get("ui.font_scale") == 1.25, str(on_disk))
    check("clamp 上界 -> 1.6", EditorSettings.set("ui.font_scale", 5.0) == 1.6)
    check("clamp 下界 -> 0.7", EditorSettings.set("ui.font_scale", 0.1) == 0.7)
    check("非法数值 -> 默认 1.0", EditorSettings.set("ui.font_scale", "abc") == 1.0)
    check("已发布 zh 可选", EditorSettings.set("ui.language", "zh") == "zh")
    check("枚举越界 -> 默认 en", EditorSettings.set("ui.language", "fr") == "en")
    check("Port clamp 上界 -> 65535", EditorSettings.set("server.port", 70000) == 65535)
    check("Port clamp 下界 -> 1024", EditorSettings.set("server.port", 80) == 1024)
    check("Port 落盘为整数", isinstance(EditorSettings.get("server.port"), int),
          repr(EditorSettings.get("server.port")))
    try:
        EditorSettings.set("no.such.key", 1)
        check("未知键 -> KeyError", False)
    except KeyError:
        check("未知键 -> KeyError", True)

    # ═══════════════════════════════════════════════════════════
    # 2b. 启动参数（Port / 语言 / 任意 Settings 键，不落盘）
    # ═══════════════════════════════════════════════════════════
    print("-- 2b. startup options --")
    startup = parse_args(["--port", "8988", "--language", "zh",
                           "--set", "ui.font_scale=1.15"])
    check("启动参数解析 Port/语言/设置",
          startup == {"server.port": 8988, "ui.language": "zh", "ui.font_scale": 1.15},
          str(startup))
    EditorSettings.apply_startup_overrides(startup)
    check("启动覆盖生效（不写文件）",
          EditorSettings.get("server.port") == 8988
          and EditorSettings.get("ui.language") == "zh"
          and EditorSettings.get("ui.font_scale") == 1.15)
    EditorSettings.load()
    check("重载设置后启动覆盖仍保留", EditorSettings.get("server.port") == 8988)
    try:
        parse_args(["--set", "no.such.key=1"])
        check("启动参数未知键 -> ValueError", False)
    except ValueError:
        check("启动参数未知键 -> ValueError", True)
    try:
        parse_args(["--port", "80"])
        check("启动参数端口越界 -> ValueError", False)
    except ValueError:
        check("启动参数端口越界 -> ValueError", True)
    EditorSettings._reset_for_tests()
    EditorSettings.load()

    # ═══════════════════════════════════════════════════════════
    # 3. 持久化往返 + 损坏容错
    # ═══════════════════════════════════════════════════════════
    print("-- 3. reload + corruption tolerance --")
    EditorSettings.set("ui.font_scale", 1.3)
    EditorSettings._reset_for_tests()      # 模拟重启 (内存清空, 文件保留)
    EditorSettings.load()
    check("重启后保留磁盘值 (1.3)", EditorSettings.get("ui.font_scale") == 1.3,
          repr(EditorSettings.get("ui.font_scale")))
    with open(EditorSettings.path(), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    EditorSettings._reset_for_tests()
    EditorSettings.load()
    check("损坏 JSON -> 默认值容错", EditorSettings.get("ui.font_scale") == 1.0)

    # ═══════════════════════════════════════════════════════════
    # 4. pending 应用模型 (渲染线程帧首)
    # ═══════════════════════════════════════════════════════════
    print("-- 4. pending -> apply (render-thread model) --")
    EditorSettings._reset_for_tests()
    applied: list = []
    EditorSettings.register_apply_hook("ui.font_scale", applied.append)
    EditorSettings.set("ui.font_scale", 1.15)
    check("set 不立即应用 (入队)", applied == [], str(applied))
    keys = EditorSettings.apply_pending()
    check("apply_pending 出队并调 hook", keys == ["ui.font_scale"] and applied == [1.15],
          f"{keys} {applied}")
    check("apply_pending 清空 (不重复应用)", EditorSettings.apply_pending() == [])
    applied.clear()
    EditorSettings.apply_all()
    check("apply_all 全量应用", applied == [1.15], str(applied))

    # ═══════════════════════════════════════════════════════════
    # 5. I18n
    # ═══════════════════════════════════════════════════════════
    print("-- 5. i18n --")
    set_language("en")
    en = t("settings.page.common")
    zh = ""
    check("en 词条非键名", bool(en) and en != "settings.page.common", en)
    lang = set_language("zh")
    zh = t("settings.page.common")
    check("zh 切换生效 (文案变化)", lang == "zh" and zh != en, f"{zh!r} vs {en!r}")
    check("非法语言 -> en", set_language("fr") == "en" and get_language() == "en")
    check("缺键回退键名", t("no.such.key") == "no.such.key", t("no.such.key"))

    # ═══════════════════════════════════════════════════════════
    # 6. SettingsPanel 页面注册表 (core 页与扩展页同级)
    # ═══════════════════════════════════════════════════════════
    print("-- 6. settings page registry --")
    ids = [p.id for p in SettingsPanel.pages()]
    check("内置两页 (common / export 同级)", ids == ["common", "export"], str(ids))
    check("Export 页来自迁移 (order=10)",
          [p.order for p in SettingsPanel.pages() if p.id == "export"] == [10])
    pid = SettingsPanel.register_page(
        SettingsPage(id="demo", title_key="demo", draw_fn=lambda: None, order=5))
    check("register_page 返回 id", pid == "demo")
    check("排序按 (order, id)",
          [p.id for p in SettingsPanel.pages()] == ["common", "demo", "export"],
          str([p.id for p in SettingsPanel.pages()]))
    try:
        SettingsPanel.register_page(SettingsPage(id="demo", title_key="demo", draw_fn=lambda: None))
        check("重名 -> ValueError", False)
    except ValueError:
        check("重名 -> ValueError", True)
    try:
        SettingsPanel.register_page(SettingsPage(id="", title_key="x", draw_fn=lambda: None))
        check("空 id -> ValueError", False)
    except ValueError:
        check("空 id -> ValueError", True)
    SettingsPanel.register_page(
        SettingsPage(id="ext_page", title_key="x", draw_fn=lambda: None, owner="demo_ext"))
    check("按 owner 清理 (扩展卸载对称)",
          SettingsPanel.unregister_pages_by_owner("demo_ext") == 1
          and "ext_page" not in [p.id for p in SettingsPanel.pages()])
    check("清理无残留 (再次调用=0)", SettingsPanel.unregister_pages_by_owner("demo_ext") == 0)
    check("unregister_page 命中 true", SettingsPanel.unregister_page("demo") is True)
    check("unregister_page 未命中 false", SettingsPanel.unregister_page("demo") is False)
    check("测试不留垃圾页", [p.id for p in SettingsPanel.pages()] == ["common", "export"])

    # ═══════════════════════════════════════════════════════════
    # 7. settings.* ops (动作单点: 与面板共用 EditorSettings)
    # ═══════════════════════════════════════════════════════════
    print("-- 7. settings.* ops --")
    EditorSettings._reset_for_tests()
    _rm_settings_file()
    EditorSettings.load()
    LiveCommandServer._register_ops()
    check("op 注册表含 settings.get / settings.set",
          "settings.get" in LiveCommandServer._ops and "settings.set" in LiveCommandServer._ops)
    got = LiveCommandServer._op_settings_get({})
    check("settings.get 省略 key = 全量", set(got.get("settings", {})) == set(DEFAULTS), str(got))
    EditorSettings.set("ui.font_scale", 1.2)
    one = LiveCommandServer._op_settings_get({"key": "ui.font_scale"})
    check("settings.get 单键", one == {"key": "ui.font_scale", "value": 1.2}, str(one))
    res = LiveCommandServer._op_settings_set({"key": "ui.language", "value": "zh"})
    check("settings.set 接受已发布语言 zh",
          res.get("value") == "zh" and EditorSettings.get("ui.language") == "zh", str(res))
    for args, label in (({}, "缺 key"), ({"key": "ui.language"}, "缺 value")):
        try:
            LiveCommandServer._op_settings_set(args)
            check(f"settings.set {label} -> ValueError", False)
        except ValueError:
            check(f"settings.set {label} -> ValueError", True)
    try:
        LiveCommandServer._op_settings_set({"key": "nope", "value": 1})
        check("settings.set 未知键 -> KeyError", False)
    except KeyError:
        check("settings.set 未知键 -> KeyError", True)

    # ── 8. 默认工作区可见性（一个面板三个标签页）──
    print("-- 8. default layout visibility --")
    import inspect
    from Application.Editor.UI.UIManager import UIManager
    from Application.Editor.Extensions.ExtensionUI import ExtensionUI
    check("Settings 默认隐藏", SettingsPanel.visible is False)
    check("默认可见面板 = Scene/Resources/Node Editor",
          UIManager.DEFAULT_VISIBLE_PANELS == {"Scene", "Resources", "Node Editor"},
          str(UIManager.DEFAULT_VISIBLE_PANELS))
    check("默认标签顺序 = Scene -> Resources -> Node Editor",
          tuple(UIManager.DEFAULT_PANEL_ORDER) ==
          ("Scene", "Resources", "Node Editor"),
          str(UIManager.DEFAULT_PANEL_ORDER))
    check("默认停靠 = 菜单栏下完整宽度",
          abs(UIManager.DEFAULT_DOCK_RIGHT_FRACTION - 1.0) < 1e-9,
          str(UIManager.DEFAULT_DOCK_RIGHT_FRACTION))
    check("三个主面板默认停靠右侧列 (0.30)",
          abs(UIManager.DEFAULT_PANEL_DOCK_FRACTION - 0.30) < 1e-9,
          str(UIManager.DEFAULT_PANEL_DOCK_FRACTION))
    check("扩展窗口默认隐藏",
          inspect.signature(ExtensionUI.register_window)
          .parameters["visible"].default is False)

    # Add Node 落点: 画布中心连续 Add 不能完全重叠（否则看起来像只成功一次）
    from Application.Core.NodeGraph import NodeCanvas
    from Application.Editor.UI.panels.node_editor.panel import _free_node_position
    canvas = NodeCanvas()
    first = _free_node_position(canvas, (100.0, 100.0))
    canvas.add_node("Sequence", first)
    second = _free_node_position(canvas, (100.0, 100.0))
    check("Add Node 连续落点不重叠", second != first, f"{first} -> {second}")
    SettingsPanel.visible = False   # 复位，避免影响同进程后续测试

    # ── 收尾: 复位 + 清理沙箱 ──
    EditorSettings._reset_for_tests()
    shutil.rmtree(_TMP, ignore_errors=True)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print("-" * 60)
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
