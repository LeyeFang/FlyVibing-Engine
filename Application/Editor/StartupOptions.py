"""StartupOptions — 编辑器启动参数（与 Settings 面板同键，作用于本次进程）。

支持:
  --port 8977                  等价于 --set server.port=8977（1024..65535）
  --language en|zh             等价于 --set ui.language=en|zh
  --set key=value              任意 Settings 键（可重复；value 先按 JSON 解析）
  --settings '{"ui.font_scale": 1.15}'   一次传入多个设置（JSON 对象）
  --settings-file path.json    JSON 对象文件（与 --settings 合并，--set 最后覆盖）

实例自述（**不是设置**，只进端口台账 — `Application/Editor/Services/PortLedger.py`）:
  --purpose "PIE UI 验证"       这一实例在做的事（后来者查端口时看到）
  --owner agent:xxx            归属（agent / 人）
  --tag ui --tag pie           标签（可重复）
  --touch Examples/UIShowcase  可能被写入的目录/文件（可重复）
  --note "别在此实例跑全量测试"

覆盖只作用于本次进程，不写回 `Application/Editor/Config/settings.json`；
面板里改设置仍走 `EditorSettings.set()` 持久化。未知键 / 非法端口直接启动失败，
避免"参数拼错但静默用了默认值"。

引擎启动:
  startup.bat --port 8978 --language zh --set ui.font_scale=1.15
  startup.bat --port 8979 --purpose "SetUIText PIE 验证" --owner agent:codebuddy
"""

from __future__ import annotations

import argparse
import json
import sys

from Application.Editor.EditorSettings import DEFAULTS, EditorSettings

_PORT_MIN = 1024
_PORT_MAX = 65535
_LANGUAGES = ("en", "zh")


def _parse_value(raw: str):
    """CLI 值 → Python 值: JSON 优先（true/1.2/[1,2]），否则原样字符串。"""
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _read_settings_json(text: str) -> dict:
    if text.startswith("@"):
        with open(text[1:], encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ValueError(f"--settings must be a JSON object or @file: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("--settings JSON must be an object")
    return data


def parse_instance_meta(argv: list[str] | None = None) -> dict:
    """解析实例自述参数：目的 / 归属 / 标签 / 涉及路径 / 提醒（不进 Settings）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    ns, _unknown = _build_parser().parse_known_args(args)
    meta: dict = {}
    if ns.purpose:
        meta["purpose"] = str(ns.purpose)
    if ns.owner:
        meta["owner"] = str(ns.owner)
    if ns.tag:
        meta["tags"] = [str(t) for t in ns.tag if str(t).strip()]
    if ns.touch:
        meta["touches"] = [str(t) for t in ns.touch if str(t).strip()]
    if ns.note:
        meta["notes"] = str(ns.note)
    return meta


def _build_parser() -> argparse.ArgumentParser:
    """启动参数解析器（设置键 + 实例自述；两处共用，避免重复定义）。"""
    parser = argparse.ArgumentParser(add_help=False, prog="EntryPoint")
    parser.add_argument("--port", type=int)
    parser.add_argument("--language", "--lang", dest="language")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--settings", default=None, metavar="JSON")
    parser.add_argument("--settings-file", default=None, metavar="PATH")
    # 实例自述 — 不是设置，只进端口台账（PortLedger），让后来者知道这个端口在做什么
    parser.add_argument("--purpose", default=None, metavar="TEXT")
    parser.add_argument("--owner", default=None, metavar="WHO")
    parser.add_argument("--tag", action="append", default=[], metavar="TAG")
    parser.add_argument("--touch", action="append", default=[], metavar="PATH")
    parser.add_argument("--note", default=None, metavar="TEXT")
    return parser


def parse_args(argv: list[str] | None = None) -> dict:
    """解析启动参数 → 待应用的设置 dict（不修改全局状态）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    ns, _unknown = _build_parser().parse_known_args(args)

    overrides: dict = {}
    if ns.settings_file:
        with open(ns.settings_file, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("--settings-file must contain a JSON object")
        overrides.update(data)
    if ns.settings:
        overrides.update(_read_settings_json(ns.settings))

    for item in ns.set:
        if "=" not in item:
            raise ValueError(f"--set expects KEY=VALUE, got {item!r}")
        key, raw = item.split("=", 1)
        overrides[key.strip()] = _parse_value(raw)

    if ns.port is not None:
        if not (_PORT_MIN <= ns.port <= _PORT_MAX):
            raise ValueError(f"--port must be {_PORT_MIN}..{_PORT_MAX}, got {ns.port}")
        overrides["server.port"] = ns.port
    if ns.language is not None:
        if ns.language not in _LANGUAGES:
            raise ValueError(f"--language must be one of {_LANGUAGES}, got {ns.language!r}")
        overrides["ui.language"] = ns.language

    unknown = sorted(set(overrides) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"unknown setting key(s): {', '.join(unknown)}")
    return overrides


def apply_startup_options(argv: list[str] | None = None) -> dict:
    """解析并应用到 EditorSettings（本次进程不落盘）; 返回实际生效值。"""
    meta = parse_instance_meta(argv)
    if meta:
        from Application.Editor.Services.PortLedger import configure as ledger_configure
        ledger_configure(**meta)
    overrides = parse_args(argv)
    if not overrides:
        return {}
    applied = EditorSettings.apply_startup_overrides(overrides)
    shown = ", ".join(f"{k}={applied[k]!r}" for k in sorted(applied))
    print(f"[Startup] overrides: {shown}")
    return applied


__all__ = ["apply_startup_options", "parse_args", "parse_instance_meta"]
