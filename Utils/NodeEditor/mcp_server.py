"""
MCP Server — Node Graph Editor Tools for AI Agents.

Exposes 5 tools:
  - get_rules          → 返回节点类型参考文档
  - get_scene_entities → 读取 scene 文件的实体列表
  - build_graph        → 从实验 spec JSON 构建节点图
  - validate_graph     → 验证节点图 (静态 + 干跑)
  - apply_graph        → 注入节点图到 scene 文件

启动方式:
  python Utils/NodeEditor/mcp_server.py
  fastmcp run Utils/NodeEditor/mcp_server.py
"""

import json, os, sys
from typing import Any

# ── 确保项目根在 sys.path ──
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Node Graph Editor", version="0.1.0")


# ═══════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def get_rules() -> str:
    """获取节点图完整参考文档（节点类型、连接规则、执行模型、常见模式）。

    Agent 在构建节点图之前必须调用此工具，了解所有可用节点类型及其引脚定义。
    """
    rules_path = os.path.join(os.path.dirname(__file__), "rules.md")
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8") as f:
            return f.read()
    return "ERROR: rules.md not found"


@mcp.tool()
def get_scene_entities(scene_path: str) -> dict:
    """读取 .scene 文件，返回实体名列表和 entity ID 映射。

    Args:
        scene_path: .scene 文件路径 (相对或绝对)

    Returns:
        {entities: [{id, name, components, parent_id}, ...], total: N}
    """
    if not os.path.isabs(scene_path):
        scene_path = os.path.join(_project_root, scene_path)
    if not os.path.exists(scene_path):
        return {"error": f"Scene not found: {scene_path}"}

    try:
        with open(scene_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": f"Failed to read: {e}"}

    scene = data.get("scene", data)
    entities = []
    for eid_str, ed in scene.get("entities", {}).items():
        entities.append({
            "id": int(eid_str),
            "name": ed.get("name", ""),
            "components": list(ed.get("components", {}).keys()),
            "parent_id": ed.get("parent_id"),
        })
    return {"entities": entities, "total": len(entities)}


@mcp.tool()
def build_graph(scene_path: str, experiment_spec: dict) -> dict:
    """从实验描述 spec 构建完整节点图 JSON。

    spec 结构:
    {
        "seed_dir": "Test/.../seed",       // 种子保存路径
        "seed_prefix": "MI-Seed",          // 种子文件名前缀
        "init_delay": 5.0,                 // 初始延迟 (秒)
        "trials": 60,                      // trial 总数
        "timer": "trial_phase",            // 主计时器名
        "phases": [
            {"time": 0, "type": "cue_pick",
             "random": {"min": 1, "max": 2},
             "branches": [
                 {"value": 1, "show": ["L_arrow_body","L_arrow_head"], "parallel": 11},
                 {"value": 2, "show": ["R_arrow_head","R_arrow_body"], "parallel": 12}
             ]},
            {"time": 2, "show": ["TaskCue"]},
            {"time": 6, "hide": ["L_arrow_body","L_arrow_head","R_arrow_head","R_arrow_body","TaskCue"]},
            {"time": 10, "type": "trial_end"}
        ],
        "entities": ["Cross","LeftCue","RightCue","TaskCue"],
        "pulse": null  // 可选: {count: 80, interval: 0.05, timer: "pulse",
                        //         parallel_addr: 0x3FF8, serial_port: "COM3",
                        //         encode: "MI<<6|SSSEP"}  // 可选 trigger 编码
    }

    Returns:
        {graph: {...}, node_count: N, link_count: M} 或 {error: "..."}
    """
    from Utils.NodeEditor.graph_builder import GraphBuilder

    g = GraphBuilder()
    GS, FU, GP = g.event_nodes()

    # ── 种子链 ──
    seed_dir = experiment_spec.get("seed_dir", "Test/Project/seed")
    seed_prefix = experiment_spec.get("seed_prefix", "Seed")
    date_format = f"{seed_prefix}-%Y-%m-%d-%H-%M"
    s = g.seed_chain(seed_dir, date_format)
    rs, vsd, tfw, pv, td = s
    g.link(GS, "exec", rs, "exec_in")

    # ── 实体生成 + 初始隐藏 ──
    template_names = experiment_spec.get("entities", [])
    if template_names:
        sp = g.spawn(*template_names)
        g.chain(tfw, *sp)

    # 收集所有需隐藏的实体名 (从 phases[0].branches 和 phases[6].hide)
    all_show_entities = set()
    for phase in experiment_spec.get("phases", []):
        for en in phase.get("show", []):
            all_show_entities.add(en)
        for en in phase.get("hide", []):
            all_show_entities.add(en)
        for br in phase.get("branches", []):
            for en in br.get("show", []):
                all_show_entities.add(en)

    init_hide_names = sorted(all_show_entities)
    if init_hide_names:
        hide_entry, hide_exit = g.hide(*init_hide_names)
        if template_names:
            g.link(sp[-1], "exec_out", hide_entry, "exec_in")
        last_node = hide_exit
    elif template_names:
        last_node = sp[-1]
    else:
        last_node = tfw

    # ── 变量 ──
    init_delay = experiment_spec.get("init_delay", 5.0)
    timer_name = experiment_spec.get("timer", "trial_phase")
    var_node = g.var_set("trial", 1)
    g.chain(last_node, var_node)
    last_node = var_node

    # ── Timer ──
    nt, st = g.timer(timer_name, -init_delay)
    g.chain(last_node, nt)
    last_node = st

    # ── 解析 phases ──
    phases = experiment_spec.get("phases", [])
    phase_times = [p["time"] for p in phases]
    has_pulse = bool(experiment_spec.get("pulse"))

    # Sequence 扇出数
    num_fanouts = len(phase_times) + (1 if has_pulse else 0)
    seq_pin_names = ["exec_in"] + [f"out_{i}" for i in range(num_fanouts)]
    seq = g.node("Sequence", seq_pin_names)
    g.link(FU, "exec", seq, "exec_in")

    # TimeTrigger
    tts = g.time_triggers(timer_name, *phase_times)
    for i, tt in enumerate(tts):
        g.link(seq, f"out_{i}", tt, "exec_in")

    # Pulse
    pulse_tt = None
    pulse_entry = None
    if has_pulse:
        p_spec = experiment_spec["pulse"]
        pulse_count = p_spec.get("count", 80)
        pulse_interval = p_spec.get("interval", 0.05)
        pulse_timer = p_spec.get("timer", "pulse")
        pulse_addr = p_spec.get("parallel_addr", 0x3FF8)
        pulse_port = p_spec.get("serial_port", "COM3")
        encode_mode = p_spec.get("encode")

        # pulse timer setup (在 OnGameStart)
        nt2 = g.node("NewTimer", ["exec_in", "exec_out", "Name"],
                     {"mode": "manual", "timer_name": pulse_timer})
        g.chain(last_node, nt2)
        last_node = nt2

        # pulse TT
        pulse_tt = g.time_triggers(pulse_timer, 0)[0]
        g.link(seq, f"out_{len(phase_times)}", pulse_tt, "exec_in")

        # pulse loop: VarGet("pulse_count") → Compare(lt, N) → Branch → send → inc → rearm
        vg_pc = g.var_get("pulse_count")
        cmp80 = g.compare("lt")
        c80 = g.constant(pulse_count)
        g.link(vg_pc, "Value", cmp80, "A")
        g.link(c80, "Result", cmp80, "B")
        br_p = g.branch_on((cmp80, "Result"))
        g.chain(vg_pc, br_p)

        # send
        vg_tg = g.var_get("trigger_val")
        ps = g.parallel_send(pulse_addr, (vg_tg, "Value"))
        chain_nodes = [ps]

        if pulse_port:
            vg_ss = g.var_get("sss_code")
            ss = g.serial_send(pulse_port, 115200, (vg_ss, "Value"))
            chain_nodes.append(ss)

        # inc counter
        vg_pc2 = g.var_get("pulse_count")
        sm_pc = g.scalar_math("sum", (vg_pc2, "Value"), (g.constant(1), "Result"))
        vs_pc = g.var_set_pin("pulse_count", (sm_pc, "Result"))
        chain_nodes.extend([vg_pc2, vs_pc])

        # rearm
        st_arm = g.node("SetTimer", ["exec_in", "exec_out", "Value"],
                        {"operate": "set_time", "mode": "manual",
                         "timer_name": pulse_timer, "value": -pulse_interval})
        chain_nodes.append(st_arm)

        g.chain(*chain_nodes)
        g.link(pulse_tt, "out_0", vg_pc, "exec_in")
        g.link(br_p, "True", ps, "exec_in")
        pulse_entry = vg_pc

    # ── 各 phase ──
    for i, phase in enumerate(phases):
        tt = tts[i]
        ptype = phase.get("type", "action")

        if ptype == "cue_pick":
            # 随机 + 分支
            r = phase["random"]
            rand = g.random_discrete(r["min"], r["max"])
            branches = phase.get("branches", [])

            prev_br = None
            prev_false = None
            for bi, br_data in enumerate(branches):
                cmp = g.compare("eq")
                c_val = g.constant(br_data["value"])
                g.link(rand, "Result", cmp, "A")
                g.link(c_val, "Result", cmp, "B")
                br = g.branch_on((cmp, "Result"))

                # show chain
                show_names = br_data.get("show", [])
                if show_names:
                    show_entry, show_exit = g.show(*show_names)
                else:
                    show_entry = show_exit = g.node("VarSet",
                        ["exec_in", "exec_out", "Name", "Value"],
                        {"mode": "manual", "var_name": "_dummy", "value": 0})

                # parallel send
                par_val = br_data.get("parallel")
                if par_val is not None:
                    ps = g.parallel_send(pulse_addr,
                        (g.constant(par_val), "Result"))
                    g.chain(show_exit, ps)
                    branch_exit = ps
                else:
                    branch_exit = show_exit

                if bi == 0:
                    g.link(tt, "out_0", br, "exec_in")
                    g.link(br, "True", show_entry, "exec_in")
                else:
                    g.link(prev_false, "False", br, "exec_in")
                    g.link(br, "True", show_entry, "exec_in")

                prev_br = br
                prev_false = br

        elif ptype == "action" or ptype == "show":
            show_names = phase.get("show", [])
            hide_names = phase.get("hide", [])
            if show_names:
                entry, _ = g.show(*show_names)
                g.link(tt, "out_0", entry, "exec_in")
            if hide_names:
                entry, _ = g.hide(*hide_names)
                g.link(tt, "out_0", entry, "exec_in")

        elif ptype == "trial_end":
            trials = experiment_spec.get("trials", 60)
            br_ex, exit_n, entry_vg = g.trial_counter("trial", trials)
            st_rst = g.node("SetTimer", ["exec_in", "exec_out", "Value"],
                            {"operate": "set_time", "mode": "manual",
                             "timer_name": timer_name, "value": -0.02})
            g.link(br_ex, "False", st_rst, "exec_in")
            g.link(tt, "out_0", entry_vg, "exec_in")

    # ── 构建 ──
    graph = g.build()
    return {
        "graph": graph,
        "node_count": len(graph["nodes"]),
        "link_count": len(graph["links"]),
    }


@mcp.tool()
def validate_graph(graph: dict, max_frames: int = 0, verbose: bool = False) -> dict:
    """验证节点图 (静态检查 + 可选干跑)。

    Args:
        graph: 节点图 dict (build_graph 的输出)
        max_frames: 干跑帧数 (0 = 仅静态检查)
        verbose: 详细输出

    Returns:
        {passed: bool, static_errors: [...], dry_run: {...} | null}
    """
    from Utils.NodeEditor.node_graph_validator import (
        validate_static, dry_run_simulation,
    )

    errors = validate_static(graph)
    static_errors = [{"message": e} for e in errors]

    dry_run_result = None
    if max_frames > 0 and not static_errors:
        try:
            result = dry_run_simulation(
                graph, max_frames=max_frames, verbose=verbose)
            dr_errors = result.get("errors", [])
            dry_run_result = {
                "frames_simulated": result.get("frames_simulated", 0),
                "total_events": result.get("total_events", 0),
                "events_by_type": result.get("events_by_type", {}),
                "errors": dr_errors,
            }
            passed = len(dr_errors) == 0
        except Exception as e:
            dry_run_result = {"errors": [str(e)]}
            passed = False
    else:
        passed = len(static_errors) == 0

    return {
        "passed": passed,
        "static_errors": static_errors,
        "dry_run": dry_run_result,
    }


@mcp.tool()
def apply_graph(scene_path: str, graph: dict) -> dict:
    """将节点图注入到 .scene 文件。

    Args:
        scene_path: 目标 .scene 文件路径 (相对或绝对)
        graph: 节点图 dict

    Returns:
        {success: bool, path: str, node_count: int, link_count: int}
    """
    if not os.path.isabs(scene_path):
        scene_path = os.path.join(_project_root, scene_path)

    if not os.path.exists(scene_path):
        return {"success": False, "error": f"Scene not found: {scene_path}"}

    try:
        with open(scene_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["scene"]["node_graph"] = graph
        with open(scene_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return {
            "success": True,
            "path": scene_path,
            "node_count": len(graph.get("nodes", {})),
            "link_count": len(graph.get("links", {})),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
