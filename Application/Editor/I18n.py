"""I18n — 目录驱动的 UI 翻译服务（协议: `Doc/Dev/i18n_protocol.md`）。

原则（协议 §2/§4）:
  - **目录外置**: core 词条在 `Application/Editor/Locale/<lang>.json`（env
    `MGE_LOCALE_DIR` 可覆盖 — 测试沙箱）；翻译永不进代码;
  - **源语言 = en**: 代码里的键必须在 en 目录存在（缺 = 构建错误, 由守卫拦）;
  - 扩展经 `register_catalog("ext.<id>", lang, {key: text})` 自带语言包,
    key 命名空间 `ext.<id>.*`；卸载经 `unregister_catalogs(owner)` 对称清理;
  - 回退链: 当前语言 → en → 键名原文（**永不抛错**）;
  - agent 面向文本（op 摘要 / 日志 / 文档）**不属于**本服务（协议 §4 边界表）。

用法:
    from Application.Editor.I18n import t
    imgui.text(t("settings.common.font_size"))
"""

from __future__ import annotations

from Application.Core import AppIdentity

import json
import os

# 键规范（单一权威 — 工具与守卫同源引用）: area.sub.item…，全小写点分
KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$"

_FALLBACK = "en"
CORE_OWNER = "core"
_LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Locale")

# owner → {lang → {key: text}}；core 由 Locale/*.json 装载
_OWNER_STRINGS: dict[str, dict[str, dict[str, str]]] = {}
_META: dict[str, dict] = {}                    # lang → _meta（首见者定） 
_STRINGS: dict[str, dict[str, str]] = {}       # lang → 合并视图（只读语义）
LANGS: tuple = (_FALLBACK,)
_current: str = _FALLBACK
_loaded: bool = False


# ── 装载 / 合并 ────────────────────────────────────────────────

def locale_dir() -> str:
    """目录位置（env `MGE_LOCALE_DIR` 覆盖 — 测试沙箱）。"""
    return AppIdentity.env_get("LOCALE_DIR") or _LOCALE_DIR


def _read_catalog(path: str):
    """读一个目录文件 → (meta, {key: text})；缺失/损坏 → None（不致命, 打印告警）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001 — 坏目录不阻塞编辑器启动
        print(f"[i18n] catalog load failed ({os.path.basename(path)}): {e!r}")
        return None
    if not isinstance(raw, dict):
        return None
    strings = raw.get("strings") if isinstance(raw.get("strings"), dict) else {}
    meta = raw.get("_meta") if isinstance(raw.get("_meta"), dict) else {}
    return dict(meta), {str(k): str(v) for k, v in strings.items()}


def load_core(force: bool = False) -> None:
    """装载 core 目录（`Locale/*.json`）— 幂等（force = 重读）。"""
    global _loaded
    if _loaded and not force:
        return
    base = locale_dir()
    per_lang: dict[str, dict[str, str]] = {}
    meta: dict[str, dict] = {}
    try:
        names = sorted(os.listdir(base))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".json"):
            continue
        res = _read_catalog(os.path.join(base, name))
        if res is None:
            continue
        m, strings = res
        lang = str(m.get("language") or os.path.splitext(name)[0])
        per_lang[lang] = strings
        meta[lang] = dict(m, language=lang)
    if per_lang:
        _OWNER_STRINGS[CORE_OWNER] = per_lang
        for lang, m in meta.items():
            _META.setdefault(lang, m)
    _loaded = True
    _rebuild()


def _rebuild() -> None:
    """重算合并视图与语言表（owner 顺序: core 先 → 冲突时 core 胜）。"""
    global LANGS
    merged: dict[str, dict[str, str]] = {}
    for owner in sorted(_OWNER_STRINGS):
        for lang, mapping in _OWNER_STRINGS[owner].items():
            bucket = merged.setdefault(lang, {})
            for key, text in mapping.items():
                if key in bucket and owner != CORE_OWNER:
                    continue          # 不覆盖先注册者（扩展键命名空间本应无冲突）
                bucket[key] = text
    _STRINGS.clear()
    _STRINGS.update(merged)
    rest = sorted(l for l in merged if l != _FALLBACK)
    LANGS = tuple(([_FALLBACK] if _FALLBACK in merged else []) + rest)


# ── 扩展贡献（与 ExtensionManager 的 _purge_ops/_purge_ui 对称） ──

def register_catalog(owner: str, lang: str, mapping: dict, meta: dict | None = None) -> int:
    """注册一个目录（core 之外的来源, 如 `ext.device`）。返回词条数。"""
    owner = str(owner or "").strip()
    lang = str(lang or "").strip()
    if not owner:
        raise ValueError("owner is required")
    if not lang:
        raise ValueError("lang is required")
    load_core()
    clean = {str(k): str(v) for k, v in dict(mapping or {}).items()}
    _OWNER_STRINGS.setdefault(owner, {}).setdefault(lang, {}).update(clean)
    if meta:
        _META.setdefault(lang, dict(meta, language=lang))
    _rebuild()
    return len(clean)


def unregister_catalogs(owner: str) -> int:
    """移除某来源的全部目录（core 不可移除）。返回移除的词条数。"""
    per_lang = _OWNER_STRINGS.pop(owner, None) if owner != CORE_OWNER else None
    count = sum(len(m) for m in per_lang.values()) if per_lang else 0
    _rebuild()
    return count


# ── 查询 ──────────────────────────────────────────────────────

def available_languages() -> tuple:
    """可用语言（en 恒在首位; 由目录推导 — 覆盖表/设置枚举同源）。"""
    load_core()
    return LANGS


def language_name(code: str) -> str:
    """语言显示名（取自 `_meta.name`; 惯例用该语言自称, 如 "中文"）。"""
    load_core()
    return str(_META.get(code, {}).get("name") or code)


def coverage() -> dict:
    """逐语言完备性报告（守卫与 `i18n_tool report` 同源）。"""
    load_core()
    en = set(_STRINGS.get(_FALLBACK, {}))
    out: dict = {}
    for lang in LANGS:
        keys = set(_STRINGS.get(lang, {}))
        missing = sorted(en - keys)
        pct = (100.0 * (len(en) - len(missing)) / len(en)) if en else 100.0
        out[lang] = {
            "name": language_name(lang),
            "source": bool(_META.get(lang, {}).get("source")),
            "keys": len(keys),
            "missing": missing,
            "pct": round(pct, 1),
        }
    return out


# ── 运行期 ────────────────────────────────────────────────────

def get_language() -> str:
    return _current


def set_language(lang: str) -> str:
    """切换语言（非法值 → 回退 en）。返回实际生效语言。"""
    global _current
    load_core()
    _current = lang if lang in LANGS else _FALLBACK
    return _current


def t(key: str, **fmt) -> str:
    """取翻译；回退链 当前语言 → en → key。支持 `{}` 命名占位格式化。"""
    load_core()
    text = None
    for lang in (_current, _FALLBACK):
        bucket = _STRINGS.get(lang)
        if bucket and bucket.get(key):
            text = bucket[key]
            break
    if text is None:
        return key
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def _reset_for_tests() -> None:
    """复位（清扩展目录 + 重读 core + 回 en）— 测试隔离用。"""
    global _current, _loaded
    for owner in [o for o in _OWNER_STRINGS if o != CORE_OWNER]:
        _OWNER_STRINGS.pop(owner, None)
    _META.clear()
    _current = _FALLBACK
    _loaded = False
    load_core(force=True)

