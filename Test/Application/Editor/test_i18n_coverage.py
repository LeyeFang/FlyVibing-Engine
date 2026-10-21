"""
i18n 守卫 — 目录完备性 + 未迁移文案棘轮 + 新语言并入机制（无头）。

协议: `Doc/Dev/i18n_protocol.md` §6（守卫三层 L1）。
锁定内容:
  1. 目录与语言表（en = 源语言; 语言表由目录推导）
  2. 代码键 ⊆ en / 可提取性（无 f-string、无裸动态键）/ 键规范
  3. en 与各语言键集相等 + 占位符跨语言一致 + 非空译文
  4. **棘轮**: 未迁移可见文案数 <= `Doc/Dev/i18n_baseline.json` 的 total
     （新 UI 文案必须走 t()，否则数量上升 → FAIL）
  5. **新语言并入**: 沙箱加一门语言 → 语言表/设置枚举/面板选项/切换全部自动跟随
  6. 扩展目录注册与卸载（`register_catalog` / `unregister_catalogs`）

运行: python Utils/Dev/test_runner.py --only i18n_coverage
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
_ROOT = _d
if _ROOT:
    sys.path.insert(0, _ROOT)
    sys.path.insert(0, os.path.join(_ROOT, "Utils", "Dev"))

# 沙箱: 设置文件与语言目录均不得污染开发者真实配置
_TMP = tempfile.mkdtemp(prefix="mge_i18n_")
os.environ["MGE_EDITOR_SETTINGS"] = os.path.join(_TMP, "settings.json")

from Application.Editor.EditorSettings import EditorSettings                      # noqa: E402
from Application.Core.NodeGraph.node_types import _TYPES                          # noqa: E402
from Application.Editor.DisplayLabels import component_key, group_key, node_key  # noqa: E402
from Application.Editor.UI.panels.node_editor.styling import MENU_SECTIONS               # noqa: E402
from Application.Editor.I18n import (                                             # noqa: E402
    KEY_PATTERN, all_catalog_languages, available_languages, coverage,
    font_candidates, get_language, language_name, locale_dir, register_catalog,
    set_language, t, unregister_catalogs, _reset_for_tests,
)
import i18n_tool as tool                                                          # noqa: E402
import re                                                                         # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("i18n coverage guard — catalogs / keys / placeholders / ratchet / new-language")
    print("=" * 60)
    _reset_for_tests()
    EditorSettings._reset_for_tests()

    # ═══════════════════════════════════════════════════════════
    # 1. 目录与语言表
    # ═══════════════════════════════════════════════════════════
    print("-- 1. catalogs --")
    en = tool.read_catalog("en")
    zh = tool.read_catalog("zh")
    check("en 为源语言 (_meta.source=true)", bool(en["meta"].get("source")) is True)
    check("zh 目录存在且有 _meta.name", bool(zh["meta"].get("name")))
    langs = available_languages()
    check("语言表由目录推导且 en 首位", langs[:1] == ("en",), str(langs))
    check("published zh in language choices", "zh" in langs, str(langs))
    check("zh still loaded for checks", "zh" in all_catalog_languages(),
          str(all_catalog_languages()))
    print(f"       locale dir: {locale_dir()}   languages: {', '.join(langs)}")
    cov = coverage()
    check("en 覆盖率 100%", cov["en"]["pct"] == 100.0, str(cov.get("en")))
    check("zh 覆盖 100% 且已发布",
          cov.get("zh", {}).get("pct") == 100.0
          and cov.get("zh", {}).get("released") is True, str(cov.get("zh")))

    # ═══════════════════════════════════════════════════════════
    # 2. 代码键 ⊆ en + 可提取性
    # ═══════════════════════════════════════════════════════════
    print("-- 2. code keys --")
    used, problems = tool.scan_code_keys()
    check("键全部可静态提取 (无 f-string / 裸动态键)", not problems, "; ".join(problems[:3]))
    missing = sorted(set(used) - set(en["strings"]))
    check("代码键全部存在于 en 目录", not missing, str(missing[:5]))
    print(f"       code keys: {len(used)}   (en entries: {len(en['strings'])})")

    # ═══════════════════════════════════════════════════════════
    # 3. 键集 / 规范 / 占位符 / 空译文
    # ═══════════════════════════════════════════════════════════
    print("-- 3. key set + schema + placeholders --")
    en_keys, zh_keys = set(en["strings"]), set(zh["strings"])
    check("en 与 zh 键集相等", en_keys == zh_keys,
          f"en-only={sorted(en_keys - zh_keys)[:3]} zh-only={sorted(zh_keys - en_keys)[:3]}")
    bad_schema = [k for k in en_keys if not re.match(KEY_PATTERN, k)]
    check("键名符合规范 (area.sub.item)", not bad_schema, str(bad_schema[:3]))
    empty = [k for k in zh_keys if not zh["strings"][k]]
    check("zh 无空译文", not empty, str(empty[:3]))
    mismatch = [k for k in en_keys & zh_keys
                if tool.placeholders(en["strings"][k]) != tool.placeholders(zh["strings"][k])]
    check("占位符集合跨语言一致", not mismatch, str(mismatch[:3]))
    node_missing = [node_key(t) for t in _TYPES
                    if node_key(t) not in en_keys or node_key(t) not in zh_keys]
    comp_missing = [component_key(c) for c in
                    ("Transform", "MeshRenderer", "Camera", "MediaPlayer", "Light", "TextDisplay")
                    if component_key(c) not in en_keys or component_key(c) not in zh_keys]
    group_titles: list[str] = []
    def _collect(items: list) -> None:
        for label, target in items:
            if isinstance(target, list):
                group_titles.append(label)
                _collect(target)
    for title, items in MENU_SECTIONS:
        group_titles.append(title)
        _collect(items)
    group_missing = [group_key(g) for g in group_titles
                     if group_key(g) not in en_keys or group_key(g) not in zh_keys]
    check("节点/组件显示名键完整 (node.<snake> / comp.<snake>)",
          not node_missing and not comp_missing,
          str((node_missing + comp_missing)[:5]))
    check("Add 菜单分类键完整 (menu.node_group.*)", not group_missing,
          str(group_missing[:5]))

    # ═══════════════════════════════════════════════════════════
    # 4. 棘轮: 未迁移可见文案数只减不增
    # ═══════════════════════════════════════════════════════════
    print("-- 4. ratchet (unmigrated literals) --")
    base = tool.load_baseline()
    total, offenders, per_file = tool.count_ui_literals(base)
    limit = int(base.get("total", 0))
    base_files = {str(k): int(v) for k, v in dict(base.get("files") or {}).items()}
    check("基线文件含 total + 每文件预算 files",
          "total" in base and (bool(base_files) or limit == 0),
          str(base)[:80])
    check(f"未迁移文案总数 {total} <= 基线 {limit}", total <= limit,
          f"总数超出 {total - limit} — 新 UI 必须走 t() 或加入 exempt(带 reason)")
    grown = {f: (base_files.get(f, 0), n) for f, n in per_file.items()
             if n > base_files.get(f, 0)}
    detail = "; ".join(f"{f}: {old} -> {new} (+{new - old})"
                       for f, (old, new) in sorted(grown.items(),
                                                   key=lambda kv: -(kv[1][1] - kv[1][0]))[:3])
    check("无文件超出其文案预算（新 UI 已适配）", not grown, detail or "see i18n_tool literals --list")

    # ═══════════════════════════════════════════════════════════
    # 5. 新语言并入机制（沙箱: 加一门语言 → 全链自动跟随）
    # ═══════════════════════════════════════════════════════════
    print("-- 5. new language onboarding (sandbox) --")
    work = os.path.join(_TMP, "locale")
    shutil.copytree(locale_dir(), work)
    src = tool.read_catalog("en")
    payload = {
        "_meta": {"language": "xx", "name": "Xx-Lang", "source": False,
                  "reviewed": True, "ui_complete": True,
                  "fonts": ["X:/fonts/xx.ttf"]},
        "strings": {k: f"xx {v}" for k, v in src["strings"].items()},
    }
    with open(os.path.join(work, "xx.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.environ["MGE_LOCALE_DIR"] = work
    try:
        _reset_for_tests()
        check("语言表自动包含新语言", "xx" in available_languages(),
              str(available_languages()))
        check("语言自称来自 _meta.name", language_name("xx") == "Xx-Lang", language_name("xx"))
        check("覆盖率报告含新语言", coverage().get("xx", {}).get("pct") == 100.0,
              str(coverage().get("xx")))
        check("设置服务接受新语言 (枚举动态推导)",
              EditorSettings.set("ui.language", "xx") == "xx")
        from Application.Editor.UI.panels.SettingsPanel import _lang_choices
        check("设置面板选项自动出现新语言",
              ("Xx-Lang", "xx") in _lang_choices(), str(_lang_choices()))
        check("字体候选仅靠 _meta.fonts 增量注入",
              "X:/fonts/xx.ttf" in font_candidates(), str(font_candidates()[-2:]))
        set_language("xx")
        check("切换后译文生效", t("panel.settings") == "xx Settings", t("panel.settings"))
        _reset_for_tests()
        check("未知语言仍回退 en", EditorSettings.set("ui.language", "zz") == "en")
    finally:
        os.environ.pop("MGE_LOCALE_DIR", None)
        _reset_for_tests()
        set_language("en")
        EditorSettings.set("ui.language", "en")

    # ═══════════════════════════════════════════════════════════
    # 6. 扩展目录（register_catalog / unregister_catalogs）
    # ═══════════════════════════════════════════════════════════
    print("-- 6. extension catalogs --")
    n = register_catalog("ext.demo", "zh", {"ext.demo.hello": "你好"})
    check("register_catalog 返回词条数", n == 1, str(n))
    set_language("zh")
    check("扩展词条生效 (当前语言命中)", t("ext.demo.hello") == "你好", t("ext.demo.hello"))
    set_language("en")
    check("扩展缺 en 词条 → 回退键名", t("ext.demo.hello") == "ext.demo.hello",
          t("ext.demo.hello"))
    check("owner 清理对称 (卸载扩展)", unregister_catalogs("ext.demo") == 1)
    set_language("zh")
    check("卸载后条目消失", t("ext.demo.hello") == "ext.demo.hello", t("ext.demo.hello"))
    try:
        register_catalog("", "zh", {})
        check("owner 必填 → ValueError", False)
    except ValueError:
        check("owner 必填 → ValueError", True)

    # ── 收尾 ──
    _reset_for_tests()
    set_language("en")
    EditorSettings._reset_for_tests()
    shutil.rmtree(_TMP, ignore_errors=True)

    total_checks = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print("-" * 60)
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total_checks})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
