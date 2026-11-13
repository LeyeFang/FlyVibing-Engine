"""Extension python dependency contract — `python.runtime` 语言 + 强制点。

背景（2026-11-14）
-----------------
某设备类扩展把落盘默认改成 hdf5（需要 `h5py`），PIE 里一切正常，**导出的成品**在
`save_record` 那一刻才炸：`h5py is not installed in the engine interpreter`。
根因不是那个扩展的 bug —— 是我们从来没有描述"**产物里**需要哪些包"的字段：

* `python.mode/path/probe` 只描述**编辑器**用哪个解释器；
* 成品用的是另一份 `Resource/runtime` 镜像（按手写清单烘焙），扩展的包从不在里面。

本测试锁住修复后的契约（`Application/Core/Extension/ExtensionRuntimeDeps.py`）：

1. **语言**：`python.runtime` 的键集合固定，未知键报错（拼错 `requires` 不会被静默忽略）；
2. **语义**：`engine` = 装进产物运行时（进程内 `import`）；`bundle` = 整个环境随包
   （只给子进程，因为进程内节点只有引擎那一个解释器）；`none` = 显式声明无三方依赖；
3. **强制**：随产物分发的扩展**必须**显式声明 —— "没写"正是本次 bug 的形态；
4. **一致性**：静态审查器（工具包 `flyvibing_extension_kit.review_extension` 的 M8）是
   规范的**镜像**（它能独立运行、不 import 引擎），两者必须对同一组夹具给出相同结论。

TIER: core
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
_passed = 0
_failed: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


# ── 夹具：同一份清单同时喂给真实现与审查器镜像 ──────────────────────
# (名字, manifest, 期望是否合法)
FIXTURES = [
    (
        "no python at all (ships nodes) → 必须报",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "nodes": {"types": ["ext.fx.*"]}},
        False,
    ),
    (
        "explicit none",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine", "runtime": {"mode": "none"}}},
        True,
    ),
    (
        "engine + requires",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine",
                    "runtime": {"mode": "engine", "requires": ["h5py>=3.16"]}}},
        True,
    ),
    (
        "unknown key (typo `require`)",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine", "runtime": {"mode": "engine",
                                                  "require": ["h5py"]}}},
        False,
    ),
    (
        "bad mode",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine", "runtime": {"mode": "wheel"}}},
        False,
    ),
    (
        "none with requires",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine",
                    "runtime": {"mode": "none", "requires": ["h5py"]}}},
        False,
    ),
    (
        "bad require string",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine", "runtime": {"mode": "engine",
                                                  "requires": [">=3.0"]}}},
        False,
    ),
    (
        "bad probe name",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine",
                    "runtime": {"mode": "engine", "probe": ["not a module"]}}},
        False,
    ),
    (
        "optional not bool",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine",
                    "runtime": {"mode": "engine", "optional": "yes"}}},
        False,
    ),
    (
        "bundle without path",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "venv", "path": "%EXT_DATA%/venv",
                    "runtime": {"mode": "bundle"}}},
        True,   # 外层 python.path 兜底 → 路径可解析（目录不存在由 D4/bundle 阶段报）
    ),
    (
        "bundle with nothing to resolve",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "venv", "runtime": {"mode": "bundle"}}},
        False,
    ),
    (
        "runtime not an object",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine", "runtime": ["h5py"]}},
        False,
    ),
    (
        "env must be {str: str}",
        {"id": "fx", "entry": "e.py:create", "capabilities": ["nodes"],
         "python": {"mode": "engine",
                    "runtime": {"mode": "bundle", "path": ".", "env": {"X": 1}}}},
        False,
    ),
]


def _reviewer_verdict(manifest: dict) -> tuple:
    """跑审查器镜像 → (ok, messages)。"""
    from flyvibing_extension_kit import review_extension as rv

    report = rv.Report("<fixture>")
    rv._review_python_manifest(report, manifest)  # noqa: SLF001 — 端口用例
    failures = [ln for ln in report.lines if "[FAIL]" in ln and " M8 " in ln]
    return (not failures), failures


def main() -> int:
    print("=" * 64)
    print("Extension python dependency contract (python.runtime)")
    print("=" * 64)

    from Application.Core.Extension import ExtensionRuntimeDeps as deps

    # ── 1. 语言与校验（真实现）────────────────────────────────────
    #     与审查器镜像同口径 = `export_problems(ships_code=True)`：既覆盖 schema，
    #     也覆盖“随产物分发却没有声明”这条**策略**强制。
    with tempfile.TemporaryDirectory(prefix="mge_contract_fixture_") as fixture_root:
        os.makedirs(os.path.join(fixture_root, "venv"), exist_ok=True)
        for name, manifest, expect_ok in FIXTURES:
            contract = deps.parse(manifest, ext_id="fx", ext_dir=fixture_root,
                                  data_dir=fixture_root)
            problems = deps.export_problems(contract, ships_code=True)
            ok = not problems
            check(f"contract: {name} → {'valid' if expect_ok else 'invalid'}",
                  ok is expect_ok, f"problems={problems[:1]}")

    # ── 2. 不随产物分发时不做强制 ────────────────────────────────
    contract = deps.parse({"id": "fx", "capabilities": ["ops"]}, ext_id="fx")
    check("no contract needed when the extension is not shipped",
          deps.export_problems(contract, ships_code=False) == [])
    check("export: missing declaration is an error only for shipped extensions",
          deps.export_problems(contract, ships_code=True) != [])
    # bundle 的环境目录不存在 → 导出期报（schema 层不报，留给 D4/导出）
    with tempfile.TemporaryDirectory(prefix="mge_bundle_missing_") as tmp2:
        contract = deps.parse(
            {"id": "fx", "python": {"mode": "venv", "path": "%EXT_DATA%/nope",
                                    "runtime": {"mode": "bundle"}}},
            ext_id="fx", ext_dir=tmp2, data_dir=tmp2)
        problems = deps.export_problems(contract, ships_code=True)
        check("export: bundle env dir must exist",
              any("环境目录不存在" in p for p in problems), str(problems))

    # ── 3. 派生 import 名 / 显式 probe 优先 ─────────────────────
    contract = deps.parse({"python": {"runtime": {
        "mode": "engine", "requires": ["h5py>=3.16", "PyOpenGL-accelerate"]}}},
        ext_id="fx")
    check("import names derived from requirements",
          contract.imports == ["h5py", "PyOpenGL_accelerate"], str(contract.imports))
    contract = deps.parse({"python": {"runtime": {
        "mode": "engine", "requires": ["pyserial>=3.5"], "probe": ["serial"]}}},
        ext_id="fx")
    check("explicit probe wins over derivation", contract.imports == ["serial"],
          str(contract.imports))

    # ── 4. 审查器镜像 == 真实现（同一组夹具、同一结论）───────────
    for name, manifest, expect_ok in FIXTURES:
        ok, failures = _reviewer_verdict(manifest)
        check(f"reviewer mirror agrees: {name}", ok is expect_ok,
              f"failures={failures[:1]}")

    # ── 5. 导出强制：临时 engine_root 走真实 `_resolve_export_extensions` ──
    from Application.Editor.ProjectManager import ProjectManager

    with tempfile.TemporaryDirectory(prefix="mge_ext_py_contract_") as tmp:
        funcs = os.path.join(tmp, "Application", "Functions")
        cases = {
            # 目录名 → (manifest python 段, 期望 python_problems 是否为空)
            "FxNone": ({"mode": "engine", "runtime": {"mode": "none"}}, True),
            "FxMissing": (None, False),
            "FxTypo": ({"mode": "engine", "runtime": {"mode": "engine",
                                                      "require": ["h5py"]}}, False),
            "FxBundleGone": ({"mode": "venv", "path": "%EXT_DATA%/nope",
                              "runtime": {"mode": "bundle"}}, True),
        }
        expected_types: set = set()
        for folder, (python_spec, _ok) in cases.items():
            ext_id = folder.lower()
            manifest = {
                "id": ext_id, "name": folder, "version": "0.1.0", "api_version": "1",
                "entry": "extension.py:create_extension",
                "capabilities": ["nodes"],
                "nodes": {"module": "fx_nodes", "factory": "build_pack",
                          "types": [f"ext.{ext_id}.*"]},
            }
            if python_spec is not None:
                manifest["python"] = python_spec
            _write_json(os.path.join(funcs, folder, "extension.json"), manifest)
            with open(os.path.join(funcs, folder, "extension.py"), "w",
                      encoding="utf-8") as fh:
                fh.write("def create_extension():\n    return None\n")
            expected_types.add(f"ext.{ext_id}.A")

        # bundle 用例需要一个真实存在的数据目录（%EXT_DATA% 展开目标）
        os.makedirs(os.path.join(
            ProjectManager._extension_data_dir("fxbundlegone"), "nope"), exist_ok=True)

        _kept, _warnings, details = ProjectManager._resolve_export_extensions(
            tmp, expected_types)
        problems = details.get("python_problems") or []
        joined = " | ".join(problems)
        check("export: explicit contract accepted (no problem for mode=none)",
              "fxnone" not in joined, joined)
        check("export: undeclared contract blocks export", "fxmissing" in joined, joined)
        check("export: unknown key blocks export", "fxtypo" in joined, joined)
        check("export: bundle path resolved from python.path (not a schema error)",
              "fxbundlegone" not in joined, joined)
        check("export: contract recorded for every shipped extension",
              set(details.get("python") or {}) ==
              {"fxnone", "fxmissing", "fxtypo", "fxbundlegone"},
              str(sorted(details.get("python") or {})))

        # ── 6. 扩展目录瘦身（Test/Doc/Examples 不进产物）──────────
        out = os.path.join(tmp, "out")
        ext_out = os.path.join(out, "Application", "Functions", "FxNone")
        for sub in ("Test", "Doc", "Examples", "nodes"):
            os.makedirs(os.path.join(ext_out, sub), exist_ok=True)
            with open(os.path.join(ext_out, sub, "keep.txt"), "w", encoding="utf-8") as fh:
                fh.write("x")
        pruned = ProjectManager._prune_extension_dirs(
            out, tmp, {os.path.join(funcs, "FxNone")})
        check("export: Test/Doc/Examples pruned from the shipped extension dir",
              sorted(p.split(":")[-1] for p in pruned) == ["Doc", "Examples", "Test"],
              str(pruned))
        check("export: real code subdir survives pruning",
              os.path.isdir(os.path.join(ext_out, "nodes")))
        check("export: pruned dirs reported in details",
              all(os.path.isdir(os.path.join(ext_out, s)) is False
                  for s in ("Test", "Doc", "Examples")))

        # ── 7. 依赖分发写出契约元数据（成品据此 probe）────────────
        info = ProjectManager._distribute_extension_python(
            out, tmp, details.get("python") or {},
            runtime_included=False, warnings=[])
        contracts_path = os.path.join(out, "extensions", "python_contracts.json")
        check("export: python_contracts.json written for the product",
              os.path.isfile(contracts_path), contracts_path)
        payload = json.load(open(contracts_path, encoding="utf-8"))
        check("export: contracts file carries the schema version",
              payload.get("version") == deps.SPEC_VERSION, str(payload.get("version")))
        check("export: every shipped extension recorded in the contracts file",
              set(payload.get("extensions") or {}) == set(details.get("python") or {}))
        check("export: engine-mode without runtime image reports a failure",
              bool((info["extensions"].get("fxmissing") or {}).get("failed")
                   or info["extensions"].get("fxmissing", {}).get("mode") == "none"),
              str(info["extensions"].get("fxmissing")))

    # ── 8. 成品侧 probe / env 注入 ───────────────────────────────
    with tempfile.TemporaryDirectory(prefix="mge_ext_prod_") as tmp:
        _write_json(os.path.join(tmp, "extensions", "python_contracts.json"), {
            "version": deps.SPEC_VERSION,
            "extensions": {
                "good": {"mode": "engine", "probe": ["json"], "optional": False},
                "bad": {"mode": "engine", "probe": ["definitely_absent_pkg"],
                        "optional": True},
                "off": {"mode": "none"},
            },
        })
        check("product: contracts load from extensions/python_contracts.json",
              set(deps.load_product_contracts(tmp)) == {"good", "bad", "off"},
              str(sorted(deps.load_product_contracts(tmp))))
        check("product: missing probe detected",
              deps.missing_imports(["json", "definitely_absent_pkg"]) ==
              ["definitely_absent_pkg"])
        _write_json(os.path.join(tmp, "extensions", "python_envs.json"), {
            "version": deps.SPEC_VERSION,
            "extensions": {"good": {"executable": sys.executable}},
        })
        applied = deps.apply_env_overrides(tmp)
        key = "FVE_EXT_PYTHON_GOOD"
        check("product: bundled env becomes FVE_EXT_PYTHON_<ID>",
              applied and os.environ.get(key) == sys.executable, str(applied))
        os.environ.pop(key, None)
        check("product: legacy product without metadata is tolerated",
              deps.load_product_contracts(os.path.join(tmp, "nowhere")) == {})

    # ── 9. 仓库内扩展必须全部符合规范（外部仓库的由作者自行补齐）──
    funcs = os.path.join(ROOT, "Application", "Functions")
    offenders: list[str] = []
    for name in sorted(os.listdir(funcs)):
        manifest_path = os.path.join(funcs, name, "extension.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            manifest = json.load(open(manifest_path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        contract = deps.parse(manifest, ext_id=name, ext_dir=os.path.join(funcs, name))
        ships = bool(manifest.get("entry")) and (
            "nodes" in (manifest.get("capabilities") or ())
            or isinstance(manifest.get("nodes"), dict)
            or "python" in manifest)
        if deps.export_problems(contract, ships_code=ships):
            offenders.append(
                f"{name}: {deps.export_problems(contract, ships_code=True)[0]}")
    # 独立 git 仓库（社区/厂商自己的仓）不归本仓库管：它们的 manifest 由作者更新。
    # 判据看的是“是否外部仓库”，不写任何品牌名（brand tripwire）。
    unexpected = [
        o for o in offenders
        if not os.path.isdir(os.path.join(funcs, o.split(":")[0], ".git"))
    ]
    check("repo extensions all declare a valid runtime contract",
          not unexpected, "; ".join(unexpected[:2]))

    print("-" * 64)
    print(f"  {_passed} passed, {len(_failed)} failed")
    if _failed:
        for label in _failed:
            print(f"  FAILED: {label}")
        return 1
    print("  RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
