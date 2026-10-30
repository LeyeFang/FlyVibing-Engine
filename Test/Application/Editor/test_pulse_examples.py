"""Pulse examples guard — Examples/SerialPulse & ParallelPulse + live pipeline applier.

锁定内容（Example 开发指南 / 节点开发指南）:
  1. 两个官方示例工程存在、带 provider=@Official、startup_scene 正确
  2. File ▸ Open Example 目录扫描能发现它们（含 provider 签名）
  3. 场景图自洽（连线引用的 pin 真实存在 / 单一设备发送节点 / description 带流水线标记）
  4. L2 干跑：每 60 帧（1 s @60fps）发一次，值 1..10 循环
  5. Examples/tools/pulse_pipeline.py 的 plan() 增量/覆写语义（不重复建节点）

运行: python Utils/Dev/test_runner.py --only pulse_examples
"""
# TIER: core

from __future__ import annotations

import importlib.util
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
ROOT = _d or ""
if ROOT:
    sys.path.insert(0, ROOT)

_RESULTS = {"pass": 0, "fail": 0}
EXAMPLES = os.path.join(ROOT, "Examples")
TOOLS = os.path.join(EXAMPLES, "tools")


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _load_module():
    path = os.path.join(TOOLS, "pulse_pipeline.py")
    spec = importlib.util.spec_from_file_location("pulse_pipeline_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scene(name: str) -> dict:
    import json

    path = os.path.join(EXAMPLES, name, "scenes", f"{name}.scene")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    import json

    print("=" * 60)
    print("Pulse examples — catalog / graph / dry-run / applier plan")
    print("=" * 60)

    pp = _load_module()

    # ── 1. 工程元数据 ─────────────────────────────────────────
    print("-- 1. projects --")
    for name in ("SerialPulse", "ParallelPulse"):
        proj_path = os.path.join(EXAMPLES, name, f"{name}.myproj")
        check(f"{name}.myproj exists", os.path.isfile(proj_path), proj_path)
        with open(proj_path, encoding="utf-8") as fh:
            proj = json.load(fh)
        check(f"{name} provider=@Official", proj.get("provider") == "@Official", str(proj.get("provider")))
        check(f"{name} startup scene", proj.get("startup_scene") == f"scenes\\{name}.scene",
              str(proj.get("startup_scene")))
        check(f"{name} README exists",
              os.path.isfile(os.path.join(EXAMPLES, name, "README.md")))
        check(f"{name} scene file exists",
              os.path.isfile(os.path.join(EXAMPLES, name, "scenes", f"{name}.scene")))

    # ── 2. File ▸ Open Example 目录 ───────────────────────────
    print("-- 2. catalog --")
    from Application.Editor.UI.UIManager import UIManager

    catalog = dict(UIManager._example_projects())
    for name in ("SerialPulse", "ParallelPulse"):
        check(f"catalog lists {name}", name in catalog, str(sorted(catalog)))
        check(f"catalog provider {name}",
              UIManager._example_provider(catalog[name]) == "@Official")

    # ── 3. 场景图自洽 ─────────────────────────────────────────
    print("-- 3. scene graph --")
    for name, send_type in (("SerialPulse", "SerialSend"), ("ParallelPulse", "ParallelSend")):
        scene = _scene(name)
        graph = scene["scene"]["node_graph"]
        nodes = graph["nodes"]
        links = graph["links"]
        pins = {int(pid) for nd in nodes.values() for pid in nd["pin_ids"].values()}
        dangling = [lid for lid, lk in links.items()
                    if int(lk["from_pin"]) not in pins or int(lk["to_pin"]) not in pins]
        check(f"{name}: 19 nodes", len(nodes) == 19, str(len(nodes)))
        check(f"{name}: 20 links", len(links) == 20, str(len(links)))
        check(f"{name}: no dangling links", not dangling, str(dangling))
        sends = [nd for nd in nodes.values() if nd["node_type"] == send_type]
        check(f"{name}: exactly one {send_type}", len(sends) == 1, str(len(sends)))
        marked = [nd for nd in nodes.values()
                  if str(nd.get("description", "")).startswith("[pulse:pulse:")]
        check(f"{name}: every node carries the pipeline tag", len(marked) == len(nodes),
              f"{len(marked)}/{len(nodes)}")
        check(f"{name}: startup spawns the Cross template",
              any(nd["node_type"] == "EntitySpawn" and nd["props"].get("template") == "Cross"
                  for nd in nodes.values()))
        scene_groups = scene["scene"].get("entities") or {}
        check(f"{name}: Cross template entity present",
              any(e.get("name") == "Cross" for e in scene_groups.values()))

    # ── 4. L2 干跑节奏 ────────────────────────────────────────
    print("-- 4. dry-run cadence --")
    from Application.Core.NodeGraph.validation.dry_run import run_dry_run

    serial = _scene("SerialPulse")
    res = run_dry_run(serial, frames=780, seed=0)
    sends = [item for item in res["log"] if item.get("node_type") == "SerialSend"]
    vals = [float(str(item["detail"]).split("val=")[-1]) for item in sends]
    check("serial dry-run: no errors", not res["errors"], str(res["errors"])[:200])
    check("serial dry-run: 12 pulses in 13 s", len(sends) == 12, str(len(sends)))
    check("serial dry-run: values 1..10 then wrap",
          vals == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 1, 2], str(vals))
    gaps = [b["frame"] - a["frame"] for a, b in zip(sends, sends[1:])]
    check("serial dry-run: ~1 s spacing (60 frames)", all(59 <= g <= 61 for g in gaps), str(gaps))

    parallel = _scene("ParallelPulse")
    res_p = run_dry_run(parallel, frames=780, seed=0)
    writes = [item for item in res_p["log"] if item.get("node_type") == "ParallelSend"]
    codes = []
    for item in writes:
        detail = str(item["detail"])
        codes.append(int(detail.split("val=0x")[-1].split(" ")[0], 16))
    check("parallel dry-run: no errors", not res_p["errors"], str(res_p["errors"])[:200])
    check("parallel dry-run: values 1..10 then wrap",
          codes == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 1, 2], str(codes))

    # ── 5. applier plan 语义 ──────────────────────────────────
    print("-- 5. applier plan --")
    spec = pp.build_spec("serial", port="@mydevice")
    check("spec: 19 nodes / device node last",
          len(spec["nodes"]) == 19 and spec["nodes"][-1]["type"] == "SerialSend")
    check("spec: tag parse round-trip",
          pp.parse_tag(spec["nodes"][0]["description"]) == ("pulse", "start"))
    empty_plan = pp.plan(spec, {})
    check("plan(empty): 19 creates", len(empty_plan["creates"]) == 19)
    check("plan(empty): 0 updates", not empty_plan["updates"])

    fake = {item["slot"]: {"id": 1000 + i, "props": dict(item["props"]),
                           "pins": {}, "description": item["description"]}
            for i, item in enumerate(spec["nodes"])}
    same = pp.plan(spec, fake, explicit={"port"})
    check("plan(existing, port only): 0 creates / 0 updates",
          not same["creates"] and not same["updates"], str(same["updates"]))

    fake2 = {k: dict(v) for k, v in fake.items()}
    fake2["send"] = dict(fake2["send"], props={"port": "COM9", "baud_rate": 9600, "format": "bytes"})
    port_only = pp.plan(spec, fake2, explicit={"port"})
    check("plan(explicit port): only port updated",
          len(port_only["updates"]) == 1 and port_only["updates"][0]["props"] == {"port": "@mydevice"},
          str(port_only["updates"]))
    over = pp.plan(spec, fake2, overwrite=True)
    over_send = [u for u in over["updates"] if u["slot"] == "send"]
    check("plan(overwrite): format pushed back to template",
          over_send and over_send[0]["props"].get("format") == "string", str(over_send))
    check("plan: period change syncs arm+rearm",
          len([u for u in pp.plan(pp.build_spec("serial", period=0.5), fake, explicit={"period"})["updates"]]) == 2)

    bare = pp.build_spec("serial", template="none")
    check("spec(template=none): 18 nodes / 19 links",
          len(bare["nodes"]) == 18 and len(bare["links"]) == 19,
          f"{len(bare['nodes'])}/{len(bare['links'])}")
    check("spec(template=none): start links straight to reset_index",
          ("start", "exec", "reset_index", "exec_in") in bare["links"]
          and not any("spawn" in (lk[0], lk[2]) for lk in bare["links"]))

    print("-" * 60)
    ok = _RESULTS["fail"] == 0
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
