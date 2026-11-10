"""Regression: 引擎版本 ↔ 工具链版本锁定文件必须与 pyproject 一致。

为什么需要
    发布时"引擎 1.1.0 配哪个工具链"如果只写在人脑或聊天记录里，打安装包时
    很容易拿到更新的工具链 wheel（`build_installer._install_editor_mcp` 取
    `dist/` 里最新的），导致发布的 op 契约与文档契约跟引擎不匹配。

锁定文件
    `Utils/Dev/Installer/toolchain.lock.json` — 由发布负责人手工更新；
    本测试保证它与 `pyproject.toml` 的 version 同步，并且结构完整。
"""
# TIER: core

from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_LOCK = os.path.join(_ROOT, "Utils", "Dev", "Installer", "toolchain.lock.json")
_PYPROJECT = os.path.join(_ROOT, "pyproject.toml")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _project_version() -> str:
    import tomllib

    with open(_PYPROJECT, "rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def main() -> int:
    check("lock 文件存在", os.path.isfile(_LOCK), _LOCK)
    if not os.path.isfile(_LOCK):
        print(f"RESULT: 0/1 passed")
        return 1

    with open(_LOCK, encoding="utf-8") as fh:
        lock = json.load(fh)

    ver = _project_version()
    check(f"engine_version 与 pyproject 一致（{ver}）",
          str(lock.get("engine_version")) == ver,
          f"lock={lock.get('engine_version')} pyproject={ver}")

    check("有 toolchain_version", bool(str(lock.get("toolchain_version") or "").strip()),
          str(lock.get("toolchain_version")))
    check("有 locked_at 日期", bool(str(lock.get("locked_at") or "").strip()),
          str(lock.get("locked_at")))

    pkgs = lock.get("packages") or {}
    check("packages 是对象且非空", isinstance(pkgs, dict) and bool(pkgs), str(type(pkgs)))
    for name in ("engine-editor-mcp", "flyvibing-extension-kit", "flyvibing-node-editor"):
        check(f"记录 {name} 版本", bool(str(pkgs.get(name) or "").strip()),
              str(pkgs))

    # 版本号形态: 三段数字
    def _semver_like(v: str) -> bool:
        parts = str(v).split(".")
        return len(parts) == 3 and all(p.isdigit() for p in parts)

    check("toolchain_version 形如 X.Y.Z",
          _semver_like(str(lock.get("toolchain_version") or "")),
          str(lock.get("toolchain_version")))
    check("engine_version 形如 X.Y.Z", _semver_like(ver), ver)

    # 工具仓在场时交叉校验 VERSION（不在场时跳过 —— 单仓 checkout）
    tools_version = os.path.join(os.path.dirname(_ROOT),
                                 "FlyVibing-User-And-Developer-Utils", "VERSION")
    if os.path.isfile(tools_version):
        with open(tools_version, encoding="utf-8") as fh:
            actual = fh.read().strip()
        check(f"工具仓 VERSION 与锁定一致（{actual}）",
              actual == str(lock.get("toolchain_version")),
              f"lock={lock.get('toolchain_version')} repo={actual}")
    else:
        print("  [SKIP] 工具仓不在同级目录 — 跳过 VERSION 交叉校验")

    # 安装器模板版本必须与 pyproject 同步（1.0.3 曾长期落后于 pyproject）
    iss = os.path.join(_ROOT, "Utils", "Dev", "Installer", "installer.iss")
    if os.path.isfile(iss):
        with open(iss, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.strip().startswith("#define AppVersion"):
                    quoted = line.split('"')
                    iss_ver = quoted[1] if len(quoted) > 1 else ""
                    check(f"installer.iss AppVersion 与 pyproject 一致（{iss_ver}）",
                          iss_ver == ver, f"iss={iss_ver} pyproject={ver}")
                    break
    else:
        print("  [SKIP] installer.iss 不存在")

    print(f"RESULT: {_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']} passed, "
          f"{_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
