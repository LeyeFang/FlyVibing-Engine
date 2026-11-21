"""内置扩展判定守卫（2026-11-10 修正：内置 ≠ 「在 Application/Functions 里」）。

背景（社区夹具作者报告"示例注入不生效"后定位到的事实）：
  `Application/Functions/` 里既有主线内置扩展（随引擎/安装包分发），也常驻本地/社区
  夹具（整个目录在 .gitignore 里）。早期实现用「位于 Functions ⇒ bundled ⇒ 恒激活、
  不可停用」判定，会把这类夹具误当成内置：
    - 用户无法停用它们；
    - 文档/设置页把它们标成"内置"，与实际分发方式不符。

现在的口径（唯一实现：`ExtensionManager.scope_of`）：
    builtin = 位于 Functions **且** ∈ allowlist（`official_extensions.json` ∪
              `.gitignore` 白名单 `!Application/Functions/<Dir>/`）→ 恒激活
    local   = 位于 Functions 但**不在** allowlist（本地/社区夹具）→ opt-in
    user    = 用户目录（%APPDATA%/FlyVibingEngine/extensions）→ opt-in

锁定:
  1. allowlist 目录集 == .gitignore 白名单目录集（两处互为镜像，漂移即红）；
  2. allowlist 每个目录都存在、manifest id 与登记 id 一致；
  3. `scope_of` 三态判定（内置 / 本地夹具 / 用户目录）；
  4. allowlist 之外的 Functions 子目录一律 local（本地夹具不能被当内置）；
  5. `to_dict()["scope"]` 与 `always_on` 的对应关系（只有 builtin 可恒激活）。

运行: python Utils/Dev/test_runner.py --only extension_builtin_scope
"""
# TIER: core

from __future__ import annotations

import json
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
_ROOT = _d
while _ROOT and not os.path.exists(os.path.join(_ROOT, "_path_setup.py")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT:
    sys.path.insert(0, _ROOT)
    import _path_setup  # noqa: E402,F401
_REPO = os.path.dirname(_ROOT) if _ROOT else ""
_FUNCS = os.path.join(_REPO, "Application", "Functions")

from Test.Helpers.tree import is_vendor_dir  # noqa: E402  (第三方目录判定单源)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _manifest_dirs() -> dict:
    """`Application/Functions/**/extension.json` → {目录绝对路径: manifest id}。"""
    found: dict = {}
    if not os.path.isdir(_FUNCS):
        return found
    for cur, dirs, files in os.walk(_FUNCS):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "_archive")
                   and not is_vendor_dir(d)]
        if "extension.json" not in files:
            continue
        try:
            with open(os.path.join(cur, "extension.json"), "r", encoding="utf-8") as fh:
                found[cur] = str(json.load(fh).get("id") or "")
        except Exception:  # noqa: BLE001 — 坏清单由 extension_boundary 负责报
            found[cur] = ""
    return found


def main() -> int:
    print("=" * 60)
    print("extension builtin scope guard (allowlist != directory)")
    print("=" * 60)

    from Application.Editor.Extensions.ExtensionManager import ExtensionManager, ExtensionInfo

    # ── 1. 两个"内置"信号必须互为镜像 ──
    print("── allowlist mirror ──")
    allow = ExtensionManager.builtin_allowlist()
    ignore_dirs = ExtensionManager.gitignore_builtin_dirs()
    check("allowlist manifest readable", allow["ok"], allow["source"])
    check("allowlist is non-empty", bool(allow["dirs"]), str(allow["dirs"]))
    check("allowlist dirs == .gitignore whitelist dirs", allow["dirs"] == ignore_dirs,
          f"allowlist-only={sorted(allow['dirs'] - ignore_dirs)} "
          f"gitignore-only={sorted(ignore_dirs - allow['dirs'])}")
    check("allowlist ids match dir count", len(allow["ids"]) == len(allow["dirs"]),
          f"ids={sorted(allow['ids'])} dirs={sorted(allow['dirs'])}")

    # ── 2. allowlist 指向真实扩展（目录存在 + id 一致）──
    print("── allowlist points at real extensions ──")
    manifests = _manifest_dirs()
    by_dir = {os.path.normcase(os.path.basename(p)): (p, mid) for p, mid in manifests.items()}
    missing_dirs, id_mismatch = [], []
    for entry_dir in allow["dirs"]:
        hit = by_dir.get(entry_dir)
        if hit is None:
            missing_dirs.append(entry_dir)
            continue
        path, mid = hit
        if mid and mid not in allow["ids"]:
            id_mismatch.append(f"{entry_dir}:{mid}")
    check("every allowlist dir exists with a manifest", not missing_dirs, str(missing_dirs))
    check("manifest ids match allowlist ids", not id_mismatch, str(id_mismatch))

    # ── 3. scope_of 三态 ──
    print("── scope_of classification ──")
    builtin_paths = [by_dir[d][0] for d in allow["dirs"] if d in by_dir]
    check("allowlisted dir -> builtin",
          bool(builtin_paths)
          and all(ExtensionManager.scope_of(p) == "builtin" for p in builtin_paths),
          str([(os.path.basename(p), ExtensionManager.scope_of(p)) for p in builtin_paths]))

    local_paths = [p for p in manifests
                   if os.path.normcase(os.path.basename(p)) not in allow["dirs"]]
    check("non-allowlisted Functions dir -> local",
          all(ExtensionManager.scope_of(p) == "local" for p in local_paths),
          str([(os.path.basename(p), ExtensionManager.scope_of(p)) for p in local_paths]))
    # 本地/社区夹具在本机存在时必须判为 local —— 这条是本次事故的回归
    #   （不在测试里点名具体夹具: Application/Test 全树禁止品牌字样，且夹具在干净克隆中不存在）

    user_like = os.path.join(os.path.expanduser("~"), "__fve_scope_probe__")
    check("path outside Functions -> user",
          ExtensionManager.scope_of(user_like) == "user",
          ExtensionManager.scope_of(user_like))
    check("id fallback: allowlist id wins over directory name",
          ExtensionManager.scope_of(os.path.join(_FUNCS, "__renamed__"),
                                    sorted(allow["ids"])[0]) == "builtin",
          sorted(allow["ids"])[:2])

    # ── 4. to_dict 的 scope / always_on 契约 ──
    print("── info contract ──")
    builtin_info = ExtensionInfo(id="x", scope="builtin", bundled=True, always_on=True)
    local_info = ExtensionInfo(id="y", scope="local", bundled=False)
    user_info = ExtensionInfo(id="z", scope="user")
    rows = [builtin_info.to_dict(), local_info.to_dict(), user_info.to_dict()]
    check("to_dict keeps the three scopes",
          [r["scope"] for r in rows] == ["builtin", "local", "user"], str(rows[0]["scope"]))
    check("only builtin can be always_on",
          rows[0]["always_on"] is True and rows[1]["always_on"] is False
          and rows[2]["always_on"] is False, str([r["always_on"] for r in rows]))

    # ── 5. 缓存只影响性能，不影响判定 ──
    print("── cache consistency ──")
    first = set(ExtensionManager.builtin_dirs())
    ExtensionManager._builtin_cache = None
    second = set(ExtensionManager.builtin_dirs())
    check("builtin_dirs stable across cache reset", first == second,
          f"{sorted(first)} vs {sorted(second)}")
    check("builtin_dirs == allowlist dirs ∪ gitignore dirs",
          second == (allow["dirs"] | ignore_dirs), str(sorted(second)))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
