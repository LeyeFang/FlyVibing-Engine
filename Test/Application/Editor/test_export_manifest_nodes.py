"""Game export — manifest-declared node types + explicit degradation.

锁住 2026-11-11 的两条约定（见 `Doc/Dev/export_distribution_plan.md`）:

* **A. 清单声明** — `extension.json` 的 `nodes.types` 是导出解析的**离线**来源：
  只读 JSON，不导入模块，因此**不要求扩展已启用**、也不要求仓库里有
  `node_pack.py`。旧实现只看运行时 registry，于是"这个编辑器会话恰好 enable
  了扩展"才能导出对应节点 —— 同一工程开关扩展会得到不同产物。

* **B. 导出 / 分发双轴** — `export:false` 只表达"禁止再分发"，不再等同于
  "别进任何产物"；`deploy:"local"` 表示"可打进本机产物"。两者组合
  （`export:false` + `deploy:"local"`）→ 目录照收，但清单记
  `local_only` / `redistributable=false`。

* **D. 显式降级** — 成品缺扩展时 `PlayerBootstrap._report_missing_node_types`
  必须报告，不能静默渲染空跑。

TIER: core
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
_passed = 0
_failed: list[str] = []

# 与真扩展无冲突的类型前缀（避免依赖被 gitignore 的本地夹具）
FX = "ext.zzfixture"


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


def _make_extension(funcs: str, folder: str, manifest: dict) -> str:
    """在临时 engine_root 下建一个扩展目录（**故意不放 node_pack.py**）。"""
    ext_dir = os.path.join(funcs, folder)
    manifest = dict(manifest)
    manifest.setdefault("entry", "extension.py:create_extension")
    _write_json(os.path.join(ext_dir, "extension.json"), manifest)
    with open(os.path.join(ext_dir, "extension.py"), "w", encoding="utf-8") as fh:
        fh.write("def create_extension():\n    return None\n")
    return os.path.abspath(ext_dir)


def main() -> int:
    print("=" * 60)
    print("Game export — manifest node types / explicit degradation")
    print("=" * 60)

    from Application.Core.NodeGraph.node_packs import NodePackRegistry
    from Application.Editor.ProjectManager import ProjectManager

    # ── 1. 清单解析（纯离线，不导入任何扩展模块）────────────────────────
    with tempfile.TemporaryDirectory(prefix="mge_manifest_nodes_") as tmp:
        engine_root = os.path.join(tmp, "engine")
        funcs = os.path.join(engine_root, "Application", "Functions")

        declared = _make_extension(funcs, "FxDeclared", {
            "id": "zzfixture", "name": "Fixture Declared",
            "version": "0.1.0", "api_version": "1",
            "capabilities": ["nodes"],
            "nodes": {"module": "fx_nodes", "factory": "build_pack",
                      "dir": ".", "types": [f"{FX}.*"]},
        })
        exact = _make_extension(funcs, "FxExact", {
            "id": "zzexact", "name": "Fixture Exact",
            "version": "0.1.0", "api_version": "1",
            "nodes": {"types": [f"{FX}OnlyNode"]},
        })
        local_only_dir = _make_extension(funcs, "FxLocal", {
            "id": "zzlocal", "name": "Fixture Local",
            "version": "0.1.0", "api_version": "1", "export": False,
            "deploy": "local",
            "nodes": {"types": [f"{FX}Local.*"]},
        })
        veto_dir = _make_extension(funcs, "FxVeto", {
            "id": "zzveto", "name": "Fixture Veto",
            "version": "0.1.0", "api_version": "1", "export": False,
            "nodes": {"types": [f"{FX}Veto.*"]},
        })
        nested_dir = os.path.join(funcs, "FxNested", "nodes")
        _write_json(os.path.join(funcs, "FxNested", "extension.json"), {
            "id": "zznested", "name": "Fixture Nested",
            "version": "0.1.0", "api_version": "1",
            "entry": "extension.py:create_extension",
            "nodes": {"dir": "nodes", "types": [f"{FX}Nested.*"]},
        })
        with open(os.path.join(funcs, "FxNested", "extension.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def create_extension():\n    return None\n")
        nested_dir = os.path.abspath(nested_dir)
        # 坏清单必须被跳过，不能阻断整个索引
        os.makedirs(os.path.join(funcs, "FxBroken"), exist_ok=True)
        with open(os.path.join(funcs, "FxBroken", "extension.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ this is not json")
        # 无 nodes 声明的扩展不进索引（继续走 node_pack.py 约定）
        _make_extension(funcs, "FxNoNodes", {
            "id": "zznodes", "name": "Fixture No Nodes",
            "version": "0.1.0", "api_version": "1",
        })

        index = NodePackRegistry.manifest_node_index([Path(funcs)])
        ids = sorted({str(m.get("id")) for _p, _d, m in index})
        check("manifest index skips bad / nodes-less manifests",
              ids == ["zzexact", "zzfixture", "zzlocal", "zznested", "zzveto"],
              str(ids))
        check("manifest index resolves trailing-slash-free dir",
              any(d == declared for _p, d, _m in index), str([d for _p, d, _m in index]))
        check("manifest index honours nodes.dir subfolder",
              any(d == nested_dir for _p, d, _m in index),
              str([d for _p, d, _m in index]))

        # ── 2. 通配 / 精确 / 不误匹配 ──
        check("prefix pattern matches", NodePackRegistry._pattern_matches(f"{FX}.*", f"{FX}.Init"))
        check("exact pattern matches", NodePackRegistry._pattern_matches(
            f"{FX}OnlyNode", f"{FX}OnlyNode"))
        check("exact pattern is not a prefix match",
              not NodePackRegistry._pattern_matches(f"{FX}OnlyNode", f"{FX}OnlyNodeX"))
        check("wildcard does not over-match sibling prefix",
              not NodePackRegistry._pattern_matches(f"{FX}.*", f"{FX}x.Init"))

        # ── 3. 离线解析：扩展**从未注册**也能找到目录 ──
        check("fixture pack is NOT registered (offline proof)",
              not any(NodePackRegistry.is_registered(t) for t in
                      (f"{FX}.Init", f"{FX}OnlyNode", f"{FX}Local.Init")),
              str(NodePackRegistry.packs()))

        dirs, unresolved = NodePackRegistry.extension_dirs_for_types(
            {f"{FX}.Init", f"{FX}.GetData"}, engine_root=engine_root)
        check("wildcard type resolves to declaring extension (offline)",
              dirs == {declared}, f"{dirs} vs {declared}")
        check("resolved types leave nothing unresolved", not unresolved, str(unresolved))

        dirs, unresolved = NodePackRegistry.extension_dirs_for_types(
            {f"{FX}OnlyNode"}, engine_root=engine_root)
        check("exact type resolves to its extension", dirs == {exact}, str(dirs))

        dirs, unresolved = NodePackRegistry.extension_dirs_for_types(
            {f"{FX}.Init", f"{FX}Nope"}, engine_root=engine_root)
        check("undeclared type stays unresolved while declared one resolves",
              dirs == {declared} and unresolved == {f"{FX}Nope"},
              f"dirs={dirs} unresolved={unresolved}")

        # ── 4. 导出 / 分发双轴 ──
        _kept, warnings, details = ProjectManager._resolve_export_extensions(
            engine_root, {f"{FX}.Init"})
        check("deploy:local keeps the directory", _kept == {declared}, str(_kept))
        check("plain extension stays redistributable",
              details["redistributable"] is True and details["local_only"] == [],
              str(details))

        kept_local, local_warnings, local_details = ProjectManager._resolve_export_extensions(
            engine_root, {f"{FX}Local.Init"})
        check("export:false + deploy:local still lands in the product",
              kept_local == {local_only_dir}, str(kept_local))
        check("export:false + deploy:local marks local_only",
              local_details["local_only"] == ["zzlocal"], str(local_details["local_only"]))
        check("export:false + deploy:local clears redistributable",
              local_details["redistributable"] is False, str(local_details))
        check("export:false + deploy:local warns about redistribution",
              any("LOCAL use only" in w for w in local_warnings), str(local_warnings))
        check("deploy mode is recorded in detail payload",
              local_details["deploy"].get("zzlocal") == "local",
              str(local_details["deploy"]))

        kept_veto, veto_warnings, veto_details = ProjectManager._resolve_export_extensions(
            engine_root, {f"{FX}Veto.Init"})
        check("export:false without deploy stays excluded",
              kept_veto == set() and veto_details["local_only"] == [], str(kept_veto))
        check("excluded extension is reported, not silent",
              any("zzveto" in w and "export:false" in w for w in veto_warnings),
              str(veto_warnings))
        check("veto does not taint redistributable", veto_details["redistributable"] is True,
              str(veto_details))

        # ── 4b. 目录筛选层不得二次否决（2026-11-11 实测缺陷）──
        real_required = {k for k in kept_local}
        excluded = ProjectManager._export_excluded_paths(
            engine_root, real_required)
        check("excluded-path filter keeps deploy:local extension",
              local_only_dir not in excluded, str(sorted(excluded)))
        check("excluded-path filter still drops out-of-scope extensions",
              veto_dir in excluded and exact in excluded, str(sorted(excluded)))
        legacy = ProjectManager._export_excluded_paths(engine_root)
        check("legacy whole-tree mode still honours export:false",
              local_only_dir in legacy and veto_dir in legacy, str(sorted(legacy)))

        # ── 5. 既有 node_pack.py 约定不受影响（真仓库）──
        real_dirs, real_unresolved = NodePackRegistry.extension_dirs_for_types({"SerialSend"})
        check("conventional node_pack.py resolution still works",
              os.path.abspath(os.path.join(ROOT, "Application", "Functions",
                                           "SerialParallelDevice")) in real_dirs
              and not real_unresolved, f"{real_dirs} {real_unresolved}")

    # ── 6. 显式降级：缺扩展必须被报告 ────────────────────────────────
    from Application.Core.NodeGraph.canvas import NodeCanvas
    from Application.Runtime.PlayerBootstrap import (
        _MISSING_NODE_TYPES,
        _report_missing_node_types,
    )

    canvas = NodeCanvas.from_dict({
        "next_id": 10,
        "nodes": {
            "1": {"node_type": "OnFrameUpdate", "pos": [0.0, 0.0], "pin_ids": {}},
            "2": {"node_type": f"{FX}.Gone", "pos": [0.0, 0.0], "pin_ids": {}},
            "3": {"node_type": f"{FX}.Gone", "pos": [0.0, 0.0], "pin_ids": {}},
        },
        "links": {},
    })
    reported = _report_missing_node_types(canvas)
    check("missing extension nodes are reported",
          reported.get(f"{FX}.Gone") == [2, 3], str(reported))
    check("degradation state is queryable by the host",
          _MISSING_NODE_TYPES.get(f"{FX}.Gone") == [2, 3],
          str(_MISSING_NODE_TYPES))

    clean = NodeCanvas.from_dict({
        "next_id": 5,
        "nodes": {"1": {"node_type": "OnFrameUpdate", "pos": [0.0, 0.0], "pin_ids": {}}},
        "links": {},
    })
    check("healthy graph reports nothing", _report_missing_node_types(clean) == {})
    check("healthy graph clears the degradation state",
          _MISSING_NODE_TYPES == {},
          str(_MISSING_NODE_TYPES))

    print()
    print("=" * 60)
    total = _passed + len(_failed)
    print(f"Results: {_passed}/{total} passed, {len(_failed)} failed")
    print("ALL TESTS PASSED" if not _failed else "TESTS FAILED")
    return 0 if not _failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
