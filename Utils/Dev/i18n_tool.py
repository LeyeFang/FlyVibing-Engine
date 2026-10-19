"""i18n_tool — 键提取 / 目录校验 / 覆盖率报告 / 新语言骨架（零依赖, stdlib）。

协议: `Doc/Dev/i18n_protocol.md`（§5 工具链 / §6 守卫 / §7 新增语言 Runbook）。

用法:
    python Utils/Dev/i18n_tool.py report              # 覆盖率表
    python Utils/Dev/i18n_tool.py extract [--add]     # 代码键 vs en 目录（--add 补空骨架）
    python Utils/Dev/i18n_tool.py check [--lang zh]   # CI 门（缺键/多键/占位符/键规范）
    python Utils/Dev/i18n_tool.py add-lang ja         # 新语言骨架 + 后续步骤提示

退出码: 0 = 通过；1 = 有 error（`check` 可直接接 CI）。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from string import Formatter

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
REPO = _d or os.getcwd()
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from Application.Editor.I18n import (  # noqa: E402
    KEY_PATTERN, _FALLBACK, all_catalog_languages, available_languages, coverage,
    load_core, locale_dir,
)

SCAN_ROOT = os.path.join(REPO, "Application", "Editor")
_KEY_RE = re.compile(KEY_PATTERN)
# 注册表"携带键"属性名: `t(x.title_key)` 属合法动态键, 键值在构造处以 `title_key="..."` 出现
# （协议 §3: 可提取性 —— 键必须能在源码里被静态找到, 这两处同时成立即可）
_KEY_CARRIER_ATTRS = ("title_key",)
# `t()` 的常见别名（`from ... import t as _t` / 局部 `tr`）
_T_ALIASES = ("t", "_t", "tr")


def _is_t_call(node: ast.Call) -> bool:
    return _call_name(node.func) in _T_ALIASES


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


# ── 代码侧键提取 ────────────────────────────────────────────────

def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def scan_code_keys() -> tuple[dict, list]:
    """AST 扫 `t("key")` + 注册表携带键（`title_key="..."`）→ ({key: [位置]}, [问题描述])。

    规则: 第一个参数必须是字符串常量（f-string / 变量 = 无法提取 → 报问题）；
    合法动态键仅限注册表携带（`t(page.title_key)` 且该页在构造处写了 `title_key="<键>"`）。
    """
    used: dict[str, list] = {}
    problems: list[str] = []
    for dirpath, _dirs, files in os.walk(SCAN_ROOT):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, REPO).replace("\\", "/")
            try:
                with open(path, encoding="utf-8-sig") as fh:   # utf-8-sig: 容忍 BOM
                    tree = ast.parse(fh.read())
            except SyntaxError as e:
                problems.append(f"{rel}: syntax error {e}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # 注册表携带键: SettingsPage(..., title_key="a.b")
                    for kw in node.keywords:
                        if (kw.arg in _KEY_CARRIER_ATTRS
                                and isinstance(kw.value, ast.Constant)
                                and isinstance(kw.value.value, str)):
                            used.setdefault(kw.value.value, []).append(f"{rel}:{node.lineno}")
                # 携带键的类属性写法: `title_key = "panel.settings"` / 带注解同形
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    val = node.value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str) and val.value:
                        for tgt in targets:
                            if _target_name(tgt) in _KEY_CARRIER_ATTRS:
                                used.setdefault(val.value, []).append(f"{rel}:{node.lineno}")
                if not isinstance(node, ast.Call) or not _is_t_call(node):
                    continue
                if not node.args:
                    problems.append(f"{rel}:{node.lineno}: t() without key")
                    continue
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    used.setdefault(a.value, []).append(f"{rel}:{node.lineno}")
                elif isinstance(a, ast.Attribute) and a.attr in _KEY_CARRIER_ATTRS:
                    pass          # 见上: 键在构造处提取
                elif isinstance(a, -sigast.JoinedStr):
                    problems.append(f"{rel}:{node.lineno}: f-string key (not extractable)")
                else:
                    problems.append(f"{rel}:{node.lineno}: dynamic key (not extractable)")
    return used, problems


# 动态显示名命名空间（节点/组件注册表在运行期拼键；由覆盖测试保证完整）
_DYNAMIC_KEY_PREFIXES = ("node.", "comp.", "menu.node_group.")


BASELINE_PATH = os.path.join(REPO, "Doc", "Dev", "i18n_baseline.json")
_SHORTCUT_RE = re.compile(r"^(Ctrl|Alt|Shift|Cmd|Meta)(\+[A-Za-z0-9]+)+$")
_FMT_RE = re.compile(r"^%[-.\d]*[dfsxXgGc]$")
_TEXT_RE = re.compile(r"[A-Za-z\u4e00-\u9fff]")
# 这些 imgui 调用的参数是**纯 id / 状态量**, 永不渲染为用户文案（协议 §6 口径）
_NON_TEXT_FUNCS = {
    "open_popup", "begin_popup", "begin_popup_modal", "begin_child", "push_id",
    "begin_disabled", "end_disabled", "set_next_window_size", "set_next_window_pos",
    "set_next_window_collapsed", "set_next_window_focus", "set_item_default_focus",
    "is_item_hovered", "is_item_clicked", "begin_group",
}


def load_baseline() -> dict:
    """读棘轮基线（`Doc/Dev/i18n_baseline.json`）。缺失 → 空 dict（守卫会要求生成）。"""
    try:
        with open(BASELINE_PATH, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _display_text(text: str) -> str:
    """imgui 显示部分（`##` 之后为 id，非文案）。"""
    return text.split("##", 1)[0]


def _is_exempt(text: str, rel: str, exempt: list) -> bool:
    for item in exempt:
        if not isinstance(item, dict) or item.get("text") != text:
            continue
        if item.get("file") and item["file"] != rel:
            continue
        return True
    return False


def count_ui_literals(baseline: dict | None = None) -> tuple[int, list, dict]:
    """盘点未迁移的**可见 UI 文案字面量** → (总数, [(file, line, text), ...], {file: 数}).

    规则（协议 §6 棘轮）:
      - 经 `t()`（含 f-string 内插值）→ 已迁移, 不计;
      - `##` 之后是 id、printf 格式、纯符号/数字 → 非文案, 不计;
      - 不渲染文案的 imgui 调用（`open_popup`/`begin_child`/`push_id` …）→ 不计;
      - 快捷键提示（`Ctrl+S` 等，边界表 §4 不翻译）→ 不计;
      - 基线 `exclude_files` / `exempt` 命中 → 不计（每条必须带 reason）。
    """
    base = baseline if baseline is not None else load_baseline()
    exclude = {str(f) for f in base.get("exclude_files", [])}
    exempt = base.get("exempt", [])
    found: list = []
    per_file: dict[str, int] = {}
    for dirpath, _dirs, files in os.walk(SCAN_ROOT):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, REPO).replace("\\", "/")
            if rel in exclude:
                continue
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr in _NON_TEXT_FUNCS:
                    continue
                base_obj = node.func.value
                if not (isinstance(base_obj, ast.Name)
                        and base_obj.id in ("imgui", "hello_imgui")):
                    continue
                args = list(node.args) + [k.value for k in node.keywords]
                for arg in args:
                    segs: list[str] = []
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        segs = [arg.value]
                    elif isinstance(arg, ast.JoinedStr):
                        segs = [v.value for v in arg.values
                                if isinstance(v, ast.Constant) and isinstance(v.value, str)]
                    if not segs:
                        continue
                    if any(isinstance(sub, ast.Call) and _is_t_call(sub)
                           for sub in ast.walk(arg)):
                        continue                     # 已走 t()
                    for seg in segs:
                        display = _display_text(seg)
                        if not _TEXT_RE.search(display) or _FMT_RE.match(seg.strip()):
                            continue
                        if _SHORTCUT_RE.match(seg.strip()):
                            continue
                        if _is_exempt(seg, rel, exempt):
                            continue
                        found.append((rel, node.lineno, seg))
                        per_file[rel] = per_file.get(rel, 0) + 1
    return len(found), found, per_file


def cmd_literals(args) -> int:
    total, found, per_file = count_ui_literals()
    base = load_baseline()
    limit = base.get("total")
    print(f"unmigrated visible UI literals: {total}   (baseline: {limit})")
    if args.write:
        payload = dict(base)
        payload.update({
            "generated": __import__("datetime").date.today().isoformat(),
            "total": total,
            "files": dict(sorted(per_file.items(), key=lambda kv: -kv[1])),
        })
        payload.setdefault("note", "棘轮基线（协议 Doc/Dev/i18n_protocol.md 6）")
        with open(BASELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"[write] {os.path.relpath(BASELINE_PATH, REPO)}  (total={total}, "
              f"files={len(per_file)})")
        return 0
    if args.list:
        for rel, ln, txt in found:
            print(f"  {rel}:{ln}  {txt[:70]!r}")
    else:
        for rel, n in sorted(per_file.items(), key=lambda kv: -kv[1])[:12]:
            print(f"  {n:4d}  {rel}")
    return 0


# ── 目录侧读取 ──────────────────────────────────────────────────
def read_catalog(lang: str) -> dict:
    path = os.path.join(locale_dir(), f"{lang}.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {"path": path, "meta": raw.get("_meta") or {}, "strings": raw.get("strings") or {}}


def placeholders(text: str) -> list[str]:
    """命名占位符列表（`{name}`）；positional `{}` 记为 "<pos>"。"""
    out: list[str] = []
    try:
        for _lit, field, _spec, _conv in Formatter().parse(text):
            if field is None:
                continue
            out.append(field.strip() or "<pos>")
    except ValueError:
        out.append("<parse-error>")
    return sorted(out)


# ── 命令 ────────────────────────────────────────────────────────

def cmd_report(_args) -> int:
    load_core()
    print(f"locale dir: {locale_dir()}")
    print(f"{'lang':6} {'name':10} {'keys':>6} {'missing':>8} {'cover':>7}  source")
    for lang, info in coverage().items():
        print(f"{lang:6} {info['name'][:10]:10} {info['keys']:6} {len(info['missing']):8} "
              f"{info['pct']:6.1f}%  {'yes' if info['source'] else ''}")
    return 0


def cmd_extract(args) -> int:
    load_core()
    used, problems = scan_code_keys()
    en = read_catalog(_FALLBACK)["strings"]
    missing = sorted(k for k in used if k not in en)
    unused = sorted(k for k in en if k not in used)
    print(f"code keys: {len(used)}   en keys: {len(en)}")
    for p in problems:
        print(f"  [PROBLEM] {p}")
    for k in missing:
        print(f"  [MISSING-IN-{_FALLBACK.upper()}] {k}   used at {', '.join(used[k][:3])}")
    for k in unused:
        print(f"  [UNUSED] {k}")
    if args.add and missing:
        for k in missing:
            en[k] = ""
        path = read_catalog(_FALLBACK)["path"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"_meta": read_catalog(_FALLBACK)["meta"], "strings": dict(sorted(en.items()))},
                      fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"[add] wrote {len(missing)} empty entries to {os.path.relpath(path, REPO)}"
              " — 必须填写源语言文案后再提交")
    return 1 if (missing or problems) and not args.add else 0


def cmd_check(args) -> int:
    load_core()
    errors: list[str] = []
    warnings: list[str] = []
    langs = [args.lang] if args.lang else list(all_catalog_languages())
    print(f"locale dir: {locale_dir()}   languages: {', '.join(langs)}")

    # 1. 源语言存在性 + 代码键 ⊆ en
    used, problems = scan_code_keys()
    errors.extend(problems)
    en = read_catalog(_FALLBACK)["strings"]
    for k in sorted(set(used) - set(en)):
        errors.append(f"key used in code but missing in {_FALLBACK}: {k} "
                      f"({', '.join(used[k][:2])})")

    # 2. 每语言: 键集 == en, 键规范, meta 完整, 占位符一致
    for lang in langs:
        try:
            cat = read_catalog(lang)
        except FileNotFoundError:
            errors.append(f"{lang}.json not found in {locale_dir()}")
            continue
        meta, strings = cat["meta"], cat["strings"]
        if not meta.get("language"):
            errors.append(f"{lang}.json: _meta.language missing")
        if not meta.get("name"):
            errors.append(f"{lang}.json: _meta.name missing (language self-name)")
        if not meta.get("reviewed", False) and lang != _FALLBACK:
            warnings.append(f"{lang}: _meta.reviewed = false (unreviewed catalog)")
        if lang != _FALLBACK and meta.get("ui_complete") and not meta.get("reviewed"):
            errors.append(f"{lang}.json: ui_complete=true requires reviewed=true")
        for k in sorted(set(strings) - set(en)):
            errors.append(f"{lang}.json: extra key not in {_FALLBACK}: {k}")
        for k in sorted(set(en) - set(strings)):
            errors.append(f"{lang}.json: missing key: {k}")
        for k, text in strings.items():
            if not _KEY_RE.match(k):
                errors.append(f"{lang}.json: key violates schema: {k!r} (see {KEY_PATTERN})")
            if not text and lang != _FALLBACK:
                errors.append(f"{lang}.json: empty translation: {k}")
            src = en.get(k)
            if src is None or not text:
                continue
            ph_src, ph_dst = placeholders(src), placeholders(text)
            if ph_src != ph_dst:
                errors.append(f"{lang}.json: placeholder mismatch for {k}: "
                              f"{_FALLBACK}={ph_src} {lang}={ph_dst}")
            if "<pos>" in ph_dst:
                errors.append(f"{lang}.json: positional placeholder not allowed for {k} "
                              "(use named placeholders)")

    # 3. 未使用键（提示级）
    for k in sorted(set(en) - set(used)):
        if k.startswith(_DYNAMIC_KEY_PREFIXES):
            continue          # 节点/组件显示名：运行期拼键，见 labels.py + 覆盖测试
        warnings.append(f"unused key in {_FALLBACK}: {k}")

    # 4. 发布门：ui_complete=true 时不得再有未迁移裸文案
    baseline_path = os.path.join(REPO, "Doc", "Dev", "i18n_baseline.json")
    try:
        with open(baseline_path, encoding="utf-8") as fh:
            baseline_total = int(json.load(fh).get("total", 0))
    except (OSError, ValueError, TypeError):
        baseline_total = -1
    for lang in all_catalog_languages():
        if lang == _FALLBACK:
            continue
        meta = read_catalog(lang)["meta"]
        if meta.get("ui_complete") and baseline_total > 0:
            errors.append(
                f"{lang}.json: ui_complete=true but UI still has {baseline_total} "
                "unmigrated literals (see i18n_baseline.json)")
        if meta.get("ui_complete") is None:
            warnings.append(f"{lang}: _meta.ui_complete missing (defaults to draft)")

    for w in warnings:
        print(f"  [WARN] {w}")
    for e in errors:
        print(f"  [ERROR] {e}")
    print(f"RESULT: {'OK' if not errors else 'FAIL'} "
          f"({len(errors)} errors, {len(warnings)} warnings)")
    if args.strict and warnings:
        return 1
    return 1 if errors else 0


def cmd_add_lang(args) -> int:
    load_core()
    lang = str(args.lang).strip()
    if not lang:
        print("usage: add-lang <code>  (e.g. ja, de, fr)")
        return 1
    path = os.path.join(locale_dir(), f"{lang}.json")
    if os.path.exists(path):
        print(f"{os.path.relpath(path, REPO)} already exists")
        return 1
    en = read_catalog(_FALLBACK)["strings"]
    payload = {
        "_meta": {"language": lang, "name": lang, "source": False,
                  "reviewed": False, "ui_complete": False, "status": "pending"},
        "strings": {k: "" for k in sorted(en)},
    }
    os.makedirs(locale_dir(), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"[add-lang] {os.path.relpath(path, REPO)} created ({len(en)} keys pending)")
    print("下一步（协议 Doc/Dev/i18n_protocol.md §7 Runbook）:")
    print("  1. 填写 en 源文案对应译文; 2. _meta.name 设为该语言自称;")
    print("  3. EditorImguiLayer.LOCALE_FONTS 增加该语言字体候选;")
    print("  4. python Utils/Dev/i18n_tool.py check --lang " + lang)
    print("  5. 字形覆盖 + 场景目视（scenarios/i18n_smoke.py）; 6. 协议表加行 + 置 reviewed;")
    print("  7. UI 裸文案全部迁移（baseline total=0）后置 ui_complete=true")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="i18n 目录工具（见 Doc/Dev/i18n_protocol.md）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_rep = sub.add_parser("report", help="覆盖率表")
    p_rep.set_defaults(func=cmd_report)
    p_ext = sub.add_parser("extract", help="代码键 vs en 目录")
    p_ext.add_argument("--add", action="store_true", help="把缺失键以空值补进 en 目录")
    p_ext.set_defaults(func=cmd_extract)
    p_chk = sub.add_parser("check", help="CI 门（缺键/多键/占位符/键规范/meta）")
    p_chk.add_argument("--lang", default="", help="只检查某语言（默认全部）")
    p_chk.add_argument("--strict", action="store_true", help="警告也算失败")
    p_chk.set_defaults(func=cmd_check)
    p_add = sub.add_parser("add-lang", help="新语言骨架 + 后续步骤")
    p_add.add_argument("lang", help="语言代码，如 ja")
    p_add.set_defaults(func=cmd_add_lang)
    p_lit = sub.add_parser("literals", help="未迁移可见文案盘点（棘轮基线口径）")
    p_lit.add_argument("--list", action="store_true", help="逐条列出")
    p_lit.add_argument("--write", action="store_true", help="刷新基线文件（total + 每文件预算）")
    p_lit.set_defaults(func=cmd_literals)
    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
