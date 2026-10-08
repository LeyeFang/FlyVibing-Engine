"""
GraphBuilder — 节点图编程式构造器。

纯数据操作, 不依赖 imgui / esper / 任何运行时。
生成符合 node_graph JSON 规范 (v0.1.0) 的 dict。

使用:
    g = GraphBuilder()
    GS, FU, GP = g.event_nodes()
    g.chain(GS, g.node("RandomSetSeed", ["exec_in","exec_out","Seed"], {"source":"hardware"}))
    ...
    report = validate(g.build(), max_frames=37000)
    if report.passed:
        g.save("scenes/MI.scene")
"""

from __future__ import annotations

import json, os
from dataclasses import dataclass, field
from typing import Optional, Callable


# ═══════════════════════════════════════════════════════════════
# 验证结果 (与 validator 耦合)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ValidationError:
    level: str = "error"
    code: str = ""
    message: str = ""
    node_id: Optional[int] = None
    detail: Optional[dict] = None


@dataclass
class ValidationReport:
    passed: bool = False
    static_errors: list[ValidationError] = field(default_factory=list)
    dry_run: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════
# GraphBuilder
# ═══════════════════════════════════════════════════════════════

class GraphBuilder:
    """节点图构造器。"""

    def __init__(self):
        self._nodes: dict[str, dict] = {}
        self._links: dict[str, dict] = {}
        self._nid = 200
        self._pid = 10000
        self._lid = 500

    # ── 低层 API ──────────────────────────────────────────

    def node(self, type_name: str, pin_names: list[str],
             props: dict = None, pos: tuple = (0, 0)) -> int:
        """创建节点并返回 node_id。"""
        nid = self._nid
        self._nid += 1
        self._nodes[str(nid)] = {
            "id": nid,
            "node_type": type_name,
            "pos": list(pos),
            "props": props or {},
            "pin_ids": {pn: self._gen_pid() for pn in pin_names},
        }
        return nid

    def link(self, fr: int, fp: str, to: int, tp: str) -> None:
        """连接两个 pin (by name)。"""
        lid = self._lid
        self._lid += 1
        self._links[str(lid)] = {
            "id": lid,
            "from_pin": self._nodes[str(fr)]["pin_ids"][fp],
            "to_pin": self._nodes[str(to)]["pin_ids"][tp],
        }

    def chain(self, *node_ids: int) -> None:
        """exec_out → exec_in 串联。"""
        for i in range(len(node_ids) - 1):
            self.link(node_ids[i], "exec_out", node_ids[i + 1], "exec_in")

    def _gen_pid(self) -> int:
        p = self._pid
        self._pid += 1
        return p

    # ── 中层 API (通用模式) ────────────────────────────────

    def event_nodes(self) -> tuple[int, int, int]:
        """创建三个事件节点 (固定 ID 161/163/166)。返回 (GS, FU, GP)。"""
        self._nodes["161"] = {"id": 161, "node_type": "OnGameStart", "pos": [80, 80],
                              "props": {}, "pin_ids": {"exec": 162}}
        self._nodes["163"] = {"id": 163, "node_type": "OnFrameUpdate", "pos": [80, 280],
                              "props": {}, "pin_ids": {"exec": 164, "delta": 165}}
        self._nodes["166"] = {"id": 166, "node_type": "OnGameStop", "pos": [80, 480],
                              "props": {}, "pin_ids": {"exec": 167}}
        return 161, 163, 166

    def timer(self, name: str, start_value: float) -> tuple[int, int]:
        """NewTimer + SetTimer(start)。返回 (new_timer_id, set_timer_id)。"""
        nt = self.node("NewTimer", ["exec_in", "exec_out", "Name"],
                       {"mode": "manual", "timer_name": name})
        st = self.node("SetTimer", ["exec_in", "exec_out", "Value"],
                       {"operate": "set_time", "mode": "manual",
                        "timer_name": name, "value": start_value})
        self.chain(nt, st)
        return nt, st

    def time_triggers(self, timer_name: str, *times: float) -> list[int]:
        """为给定 timer 创建多个 TimeTrigger。返回 [tt_id, ...]."""
        tts = []
        for t in times:
            tt = self.node("TimeTrigger",
                           ["exec_in", "exec_out", "Time", "Elapsed",
                            "out_0", "out_1", "out_2", "out_3",
                            "out_4", "out_5", "out_6", "out_7"],
                           {"mode": "manual", "time": t, "timer": timer_name})
            tts.append(tt)
        return tts

    def fan_out(self, seq_node: int, *targets: tuple[int, str]) -> None:
        """Sequence 扇出: (tt, "out_0"), (tt2, "out_1"), ..."""
        for i, (tt, _) in enumerate(targets):
            self.link(seq_node, f"out_{i}", tt, "exec_in")

    def spawn(self, *templates: str) -> list[int]:
        """EntitySpawn 多个实体。返回 [spawn_id, ...]."""
        return [self.node("EntitySpawn", ["exec_in", "exec_out", "Entity"],
                          {"template": t}) for t in templates]

    def hide(self, *entity_names: str, value: float = 0.0) -> tuple[int, int]:
        """隐藏/显示一组实体。返回 (entry_id, exit_id) — 第一个 EntityGet 和最后一个 EntitySetRenderVisible。

        原子性: 多部件需同帧显隐时请优先用 group_visible (单节点单批命令)。
        """
        entry = None
        prev = None
        for en in entity_names:
            eg = self.node("EntityGet", ["exec_in", "exec_out", "Name", "Entity"],
                           {"entity_name": en})
            es = self.node("EntitySetRenderVisible", ["exec_in", "exec_out", "EntityID", "Visible"])
            c0 = self.node("Constant", ["Result"], {"value": value})
            if prev is not None:
                self.link(prev, "exec_out", eg, "exec_in")
            else:
                entry = eg
            self.chain(eg, es)
            self.link(eg, "Entity", es, "EntityID")
            self.link(c0, "Result", es, "Visible")
            prev = es
        return entry, prev

    def group_visible(self, *entity_names: str, value: float = 1.0) -> tuple[int, int]:
        """一组实体原子显隐 (EntityGroupSetVisible) — 组内同帧生效。

        返回 (entry_id, exit_id) — 第一个 EntityGet 与最后一个组节点。
        超过 4 个实体时自动串联多个组节点 (每节点 4 个目标)。
        """
        first_entry = None
        prev_exec = None
        last = None
        for start in range(0, len(entity_names), 4):
            chunk = entity_names[start:start + 4]
            gets = [self.node("EntityGet", ["exec_in", "exec_out", "Name", "Entity"],
                              {"entity_name": en}) for en in chunk]
            gv = self.node("EntityGroupSetVisible",
                           ["exec_in", "Entity1", "Entity2", "Entity3", "Entity4",
                            "Visible", "exec_out"])
            for i, eg in enumerate(gets):
                self.link(eg, "Entity", gv, f"Entity{i + 1}")
            c0 = self.node("Constant", ["Result"], {"value": value})
            self.link(c0, "Result", gv, "Visible")
            if prev_exec is not None:
                self.link(prev_exec, "exec_out", gets[0], "exec_in")
            if first_entry is None and gets:
                first_entry = gets[0]
            for a, b in zip(gets, gets[1:]):
                self.link(a, "exec_out", b, "exec_in")
            if gets:
                self.link(gets[-1], "exec_out", gv, "exec_in")
            prev_exec = gv
            last = gv
        return first_entry, last

    def show(self, *entity_names: str) -> tuple[int, int]:
        """显示一组实体。返回 (entry_id, exit_id)。"""
        return self.hide(*entity_names, value=1.0)

    def var_set(self, name: str, value: float, mode: str = "manual") -> int:
        """VarSet (manual 模式)。"""
        return self.node("VarSet", ["exec_in", "exec_out", "Name", "Value"],
                         {"mode": mode, "var_name": name, "value": value})

    def var_set_pin(self, name: str, value_src: tuple[int, str]) -> int:
        """VarSet (pin 模式, Value 从上游读取)。"""
        vs = self.node("VarSet", ["exec_in", "exec_out", "Name", "Value"],
                       {"mode": "pin", "var_name": name})
        self.link(value_src[0], value_src[1], vs, "Value")
        return vs

    def var_get(self, name: str) -> int:
        """VarGet。"""
        return self.node("VarGet", ["exec_in", "exec_out", "Name", "Value"],
                         {"var_name": name})

    def random_discrete(self, vmin: int, vmax: int) -> int:
        """Random 离散分布。"""
        return self.node("Random", ["Min", "Max", "Mean", "StdDev", "Result"],
                         {"distribution": "discrete", "mode": "manual",
                          "min": vmin, "max": vmax})

    def branch_on(self, cond_src: tuple[int, str]) -> int:
        """Branch 读取 Condition。返回 branch_id。"""
        br = self.node("Branch", ["exec_in", "exec_out", "Condition", "True", "False"])
        self.link(cond_src[0], cond_src[1], br, "Condition")
        return br

    def compare(self, operand: str) -> int:
        """Compare 节点。"""
        return self.node("Compare", ["A", "B", "Result"], {"operation": operand})

    def constant(self, value: float) -> int:
        """Constant 节点。"""
        return self.node("Constant", ["Result"], {"value": value})

    def scalar_math(self, operand: str, *in_pairs: tuple[int, str]) -> int:
        """ScalarMath。in_pairs: [(src_node, src_pin), ...] → In_0, In_1..."""
        sm = self.node("ScalarMath",
                       ["In_0", "In_1", "Result",
                        "In_2", "In_3", "In_4", "In_5", "In_6", "In_7"],
                       {"operation": operand})
        for i, (sn, sp) in enumerate(in_pairs):
            self.link(sn, sp, sm, f"In_{i}")
        return sm

    def parallel_send(self, addr: int, value_src: tuple[int, str]) -> int:
        """ParallelSend (pin 模式)。"""
        ps = self.node("ParallelSend", ["exec_in", "exec_out", "Address", "Value"],
                       {"mode": "pin", "address": addr})
        self.link(value_src[0], value_src[1], ps, "Value")
        return ps

    def serial_send(self, port: str, baud: int,
                    value_src: tuple[int, str], fmt: str = "string") -> int:
        """SerialSend (pin 模式)。"""
        ss = self.node("SerialSend", ["exec_in", "exec_out", "Value"],
                       {"mode": "pin", "format": fmt, "port": port,
                        "baud_rate": baud})
        self.link(value_src[0], value_src[1], ss, "Value")
        return ss

    def seed_chain(self, seed_dir: str, date_format: str) -> list[int]:
        """RandomSetSeed → VarGet → TextFileWrite 种子保存链。返回 [rs, vsd, tfw] + pv, td."""
        rs = self.node("RandomSetSeed", ["exec_in", "exec_out", "Seed"],
                       {"source": "hardware"})
        vsd = self.node("VarGet", ["exec_in", "exec_out", "Name", "Value"],
                        {"var_name": "_global_random_seed"})
        pv = self.node("PathVar", ["Path"],
                       {"browse_mode": "directory", "path": seed_dir})
        td = self.node("TimeGetDate", ["DateString"],
                       {"year": True, "month": True, "day": True,
                        "hour": True, "minute": True, "format": date_format})
        tfw = self.node("TextFileWrite",
                        ["exec_in", "exec_out", "FilePath", "FileName", "Value"],
                        {"mode": "pin", "write_mode": "w", "delimiter": "newline"})
        self.chain(rs, vsd, tfw)
        self.link(pv, "Path", tfw, "FilePath")
        self.link(td, "DateString", tfw, "FileName")
        self.link(vsd, "Value", tfw, "Value")
        return [rs, vsd, tfw, pv, td]

    def trial_counter(self, var_name: str, max_trials: int) -> tuple[int, int, int]:
        """trial++, Branch(trial > max), ExitGame。
        返回 (branch, exit_node, entry_vg) — entry_vg 是链入口, branch 的 False 留给调用方接 reset。
        """
        vg = self.var_get(var_name)
        sm = self.scalar_math("sum", (vg, "Value"), (self.constant(1), "Result"))
        vs = self.var_set_pin(var_name, (sm, "Result"))
        self.chain(vg, vs)

        vg2 = self.var_get(var_name)
        cmp = self.compare("gt")
        c_max = self.constant(max_trials)
        self.link(vg2, "Value", cmp, "A")
        self.link(c_max, "Result", cmp, "B")
        br = self.branch_on((cmp, "Result"))
        self.chain(vs, vg2, br)
        exit_n = self.node("ExitGame", ["exec_in"])
        self.link(br, "True", exit_n, "exec_in")
        return br, exit_n, vg

    # ── Gtec (g.HIamp EEG) — IO ▸ Gtec ────────────────────

    def gtec_init(self, name: str = "HIAMP", *, template: str = "64ch",
                  rate: int = 512, notch: str = "off",
                  filter_type: str = "none", low_cut: float = 0.0,
                  high_cut: float = 0.0, export: str = "npz",
                  save_dir: str = ".", buffer_seconds: float = 10.0,
                  serial: str = "") -> int:
        """InitGtecDevice — 打开 + 配置 g.HIamp。

        MUST 与 gtec_kill(name) 成对出现 (validate_graph 强制检查)。
        notch: "off"/"50"/"60"; filter_type: none/highpass/lowpass/bandpass
        (截止频率 0 = 未填不生效; 与类型不匹配的字段被忽略)。
        """
        return self.node("InitGtecDevice", ["exec_in", "exec_out", "device"], {
            "device": "HIAMP", "device_name": name, "serial": serial,
            "template": template, "sampling_rate": rate,
            "notch": notch, "filter_type": filter_type,
            "low_cut": low_cut, "high_cut": high_cut,
            "export_format": export, "save_dir": save_dir,
            "buffer_seconds": buffer_seconds,
        })

    def gtec_start(self, name: str = "HIAMP", pool: str = "") -> int:
        """StartGtecRecord — 开始采集（写入窗口缓冲）。pool: 池作用域（""=旧语义）。"""
        return self.node("StartGtecRecord", ["exec_in", "exec_out"],
                         {"device_name": name, "pool": pool})

    def gtec_stop(self, name: str = "HIAMP", scope: str = "session",
                  pool: str = "") -> int:
        """StopGtecRecord — 停止采集并保存 (scope: session=全量 / buffer=窗口)。"""
        return self.node("StopGtecRecord", ["exec_in", "exec_out"],
                         {"device_name": name, "save_scope": scope, "pool": pool})

    def gtec_kill(self, name: str = "HIAMP", pool: str = "") -> int:
        """KillGtecDevice — 停止 + 释放设备（不保存）。MUST 与 gtec_init 成对。"""
        return self.node("KillGtecDevice", ["exec_in", "exec_out"],
                         {"device_name": name, "pool": pool})

    def gtec_get(self, name: str = "HIAMP", pool: str = "") -> int:
        """GetGtecData — 非销毁读取窗口缓冲（纯数据节点）。"""
        return self.node("GetGtecData", ["Data", "Channels", "Samples", "Fs"],
                         {"device_name": name, "pool": pool})

    # ── SigGen (虚拟信号发生器) — IO ▸ SigGen ─────────────

    def siggen_init(self, name: str = "SIGGEN", *, channels: int = 8,
                    rate: int = 512, frequency: float = 10.0,
                    freq_step: float = 2.0, amplitude: float = 50.0,
                    noise: float = 0.0, seed: int = 0,
                    export: str = "npz", save_dir: str = ".",
                    buffer_seconds: float = 10.0) -> int:
        """InitSigGenDevice — 虚拟信号发生器 (纯软件正弦源)。

        MUST 与 siggen_kill(name) 成对出现 (validate_graph 强制检查)。
        通道 i 频率 = frequency + i·freq_step; noise>0 时按 seed 叠加确定性噪声。
        """
        return self.node("InitSigGenDevice", ["exec_in", "exec_out", "device"], {
            "device": "VIRTUAL", "device_name": name, "channels": channels,
            "sampling_rate": rate, "frequency": frequency, "freq_step": freq_step,
            "amplitude_uv": amplitude, "noise_uv": noise, "seed": seed,
            "export_format": export, "save_dir": save_dir,
            "buffer_seconds": buffer_seconds,
        })

    def siggen_start(self, name: str = "SIGGEN", pool: str = "") -> int:
        """StartSigGenRecord — 开始采集（写入窗口缓冲）。pool: 池作用域（""=旧语义）。"""
        return self.node("StartSigGenRecord", ["exec_in", "exec_out"],
                         {"device_name": name, "pool": pool})

    def siggen_stop(self, name: str = "SIGGEN", scope: str = "session",
                    pool: str = "") -> int:
        """StopSigGenRecord — 停止采集并保存 (scope: session=全量 / buffer=窗口)。"""
        return self.node("StopSigGenRecord", ["exec_in", "exec_out"],
                         {"device_name": name, "save_scope": scope, "pool": pool})

    def siggen_kill(self, name: str = "SIGGEN", pool: str = "") -> int:
        """KillSigGenDevice — 停止 + 释放设备（不保存）。MUST 与 siggen_init 成对。"""
        return self.node("KillSigGenDevice", ["exec_in", "exec_out"],
                         {"device_name": name, "pool": pool})

    def siggen_get(self, name: str = "SIGGEN", pool: str = "") -> int:
        """GetSigGenData — 非销毁读取窗口缓冲（纯数据节点）。"""
        return self.node("GetSigGenData", ["Data", "Channels", "Samples", "Fs"],
                         {"device_name": name, "pool": pool})

    # ── Device Pool (设备池) — IO ▸ Pool ──────────────────

    def pool_create(self, name: str = "") -> int:
        """CreateDevicePool — 注册设备池。MUST 与 pool_kill(name) 成对。"""
        return self.node("CreateDevicePool", ["exec_in", "exec_out"],
                         {"pool_name": name})

    def pool_add(self, init_id: int, pool: str) -> int:
        """AddToDevicePool — 把 init_id 的 device pin 加入池。

        注意: 调用方需把返回的 Add 节点 chain 到 init 之后 (同一 exec 链)。
        """
        a = self.node("AddToDevicePool", ["exec_in", "exec_out", "device"],
                      {"pool_name": pool})
        self.link(init_id, "device", a, "device")
        return a

    def pool_kill(self, name: str = "") -> int:
        """KillDevicePool — 注销池 (成员回落 global)。MUST 与 pool_create 成对。"""
        return self.node("KillDevicePool", ["exec_in", "exec_out"],
                         {"pool_name": name})

    # ── Epoch Dataset (epoch 数据集) ──────────────────────

    def epoch_append(self, name: str = "EPOCHS") -> int:
        """EpochAppend — 追加一条 epoch (Data/Samples/Fs/Label 四线从 Get*Data 直连)。"""
        return self.node("EpochAppend",
                         ["exec_in", "exec_out", "Data", "Samples", "Fs", "Label"],
                         {"epochs_name": name})

    def epoch_count(self, name: str = "EPOCHS") -> int:
        """EpochCount — 数据集统计 (纯数据节点; Count 可接 Compare/Branch 门控)。"""
        return self.node("EpochCount", ["Count", "Classes", "Channels", "Fs"],
                         {"epochs_name": name})

    def epoch_clear(self, name: str = "EPOCHS") -> int:
        """EpochClear — 清空数据集。"""
        return self.node("EpochClear", ["exec_in", "exec_out"],
                         {"epochs_name": name})

    def epoch_save(self, name: str = "EPOCHS", save_dir: str = ".") -> int:
        """EpochSave — 落盘 npz (pad + lengths)。"""
        return self.node("EpochSave", ["exec_in", "exec_out"],
                         {"epochs_name": name, "save_dir": save_dir})

    def epoch_load(self, name: str = "EPOCHS", file_path: str = "",
                   mode: str = "replace") -> int:
        """EpochLoad — 从 npz 载入 (离线数据集入口; mode: replace/append)。"""
        return self.node("EpochLoad", ["exec_in", "exec_out"],
                         {"epochs_name": name, "file_path": file_path,
                          "mode": mode})

    # ── BCI 算法 (FBCSP / CCA) ────────────────────────────

    def fbscp_init(self, name: str = "FBCSP", n_components: int = 2,
                   classifier: str = "LDA", bands=None) -> int:
        """InitFBCSP — 注册超参集 (bands=[] → 普通 CSP)。"""
        props = {"model_name": name, "n_components": n_components,
                 "classifier": classifier}
        props["bands"] = ([[4.0, 8.0], [8.0, 13.0], [13.0, 30.0]]
                          if bands is None else [list(b) for b in bands])
        return self.node("InitFBCSP", ["exec_in", "exec_out"], props)

    def fbscp_train(self, name: str = "FBCSP", dataset: str = "EPOCHS",
                    mode: str = "train", model_path: str = "",
                    save_path: str = "") -> int:
        """TrainFBCSP — 训练/加载 (同步等待; 须挂可重复触发链)。"""
        return self.node("TrainFBCSP", ["exec_in", "exec_out"],
                         {"model_name": name, "dataset_name": dataset,
                          "mode": mode, "model_path": model_path,
                          "save_path": save_path})

    def fbscp_test(self, name: str = "FBCSP") -> int:
        """TestFBCSP — 数据进标签出 (纯数据节点)。"""
        return self.node("TestFBCSP",
                         ["Data", "Samples", "Label", "Confidence"],
                         {"model_name": name})

    def cca_test(self, freqs=None, harmonics: int = 3) -> int:
        """TestCCA — SSVEP 免训练判别 (freqs >= 2)。"""
        return self.node("TestCCA",
                         ["Data", "Samples", "Fs", "Label", "Score", "Freq"],
                         {"freqs": list(freqs or [10.0, 12.0, 15.0]),
                          "n_harmonics": harmonics})

    # ── 动态媒体 (GIF / 图像 — ShowMedia) ────────────────

    def show_media(self, update_id: int, entity_name: str) -> int:
        """ShowMedia — 挂到 update_id (如 OnFrameUpdate) 链: Get Entity → Show Media。

        Entity 直连 Get Entity.Entity; 返回 ShowMedia 节点 id (后续 exec 链续接)。
        """
        get = self.node("EntityGet", ["exec_in", "exec_out", "Name"],
                        {"entity_name": entity_name})
        show = self.node("ShowMedia", ["exec_in", "exec_out", "Entity"])
        self.link(update_id, "exec", get, "exec_in")
        self.link(get, "exec_out", show, "exec_in")
        self.link(get, "Entity", show, "Entity")
        return show

    # ── 输出 ──────────────────────────────────────────────

    def build(self, rules: str = "") -> dict:
        """构造 graph dict。"""
        all_ids = set()
        for n in self._nodes.values():
            all_ids.add(n["id"])
            for v in n["pin_ids"].values():
                all_ids.add(v)
        for l in self._links.values():
            all_ids.add(l["id"])
        result = {
            "version": "0.1.0",
            "nodes": dict(self._nodes),
            "links": dict(self._links),
            "next_id": max(all_ids) + 1 if all_ids else 200,
        }
        if rules:
            result["_rules"] = rules
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.build(), indent=indent, ensure_ascii=False)

    def validate(self, max_frames: int = 0,
                 verbose: bool = False) -> ValidationReport:
        """调用 validator 进行验证。"""
        try:
            from Utils.User.NodeEditor.node_graph_validator import (
                validate_static, dry_run_simulation,
            )
            graph = self.build()
            errors = validate_static(graph)
            static_errors = [
                ValidationError(code="static", message=e)
                for e in errors
            ]
            if static_errors:
                return ValidationReport(
                    passed=False, static_errors=static_errors)

            if max_frames > 0:
                result = dry_run_simulation(
                    graph, max_frames=max_frames, verbose=verbose)
                dry_run_errors = [
                    ValidationError(code="dry_run", message=e)
                    for e in result.get("errors", [])
                ]
                return ValidationReport(
                    passed=(len(dry_run_errors) == 0),
                    static_errors=[],
                    dry_run={
                        "frames": result.get("frames_simulated", 0),
                        "total_events": result.get("total_events", 0),
                        "events_by_type": result.get("events_by_type", {}),
                    })
            return ValidationReport(passed=True)
        except ImportError:
            return ValidationReport(
                passed=False,
                static_errors=[ValidationError(
                    code="import_error",
                    message="Cannot import validator")])

    def save(self, scene_path: str) -> bool:
        """写入 graph 到 .scene 文件 (替换其 node_graph)。"""
        if not os.path.exists(scene_path):
            print(f"[GraphBuilder] ERROR: {scene_path} not found")
            return False
        with open(scene_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["scene"]["node_graph"] = self.build()
        with open(scene_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[GraphBuilder] {len(self._nodes)} nodes, {len(self._links)} links "
              f"-> {scene_path}")
        return True
