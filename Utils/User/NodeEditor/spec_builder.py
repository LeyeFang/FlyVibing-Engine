"""实验 spec → 节点图 JSON（MCP build_graph / CLI build 共用 — 单一事实源）。

v0.2.0: 从 NodeEditor/mcp_server.build_graph 原样抽出（行为不变）。
spec 格式与示例见 rules.md 的 "build_graph Spec" 节:
    get_rules(section="build_graph Spec")  或  cli rules "build_graph Spec"
"""

from __future__ import annotations

from Utils.User.NodeEditor.graph_builder import GraphBuilder


def build_experiment_graph(experiment_spec: dict) -> dict:
    """从实验描述 spec 构建完整节点图。

    Returns: {"graph": {...}, "node_count": N, "link_count": M}
    """
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
