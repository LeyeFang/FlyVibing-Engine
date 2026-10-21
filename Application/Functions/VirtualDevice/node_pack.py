"""VirtualDevice node pack — SigGen + DevicePool 节点（2026-10-20 从核心迁出）。

节点声明与 `Core/NodeGraph/node_types` 解耦；type 名保持不变。
求值器在本目录 `evaluator_siggen.py` / `evaluator_pool.py`，由本文件注册。
本文件不得 import Editor / imgui。
"""

from __future__ import annotations


def register() -> dict:
    # Evaluators live in this extension directory; register them with the pack.
    from Application.Functions.VirtualDevice import evaluator_pool, evaluator_siggen  # noqa: F401
    pool = (0.930, 0.780, 0.220)
    sig = (0.350, 0.780, 0.850)
    return {
        "id": "virtual",
        "name": "Virtual Device",
        "owner": "virtual",
        "nodes": [
            {
                "type": "CreateDevicePool", "label": "Create Device Pool",
                "category": "Pool", "color": pool,
                "props_text": "Register a device pool (pool_name; members added via AddToDevicePool)",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
                "fields": [{"key": "pool_name", "label": "Pool Name", "kind": "text"}],
            },
            {
                "type": "AddToDevicePool", "label": "Add To Device Pool",
                "category": "Pool", "color": pool,
                "props_text": "Add the device from 'device' pin into pool_name (chain right after its Init)",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                    {"name": "device", "kind": "data", "direction": "input", "data_type": "device"},
                ],
                "fields": [{"key": "pool_name", "label": "Pool Name", "kind": "text"}],
            },
            {
                "type": "KillDevicePool", "label": "Kill Device Pool",
                "category": "Pool", "color": pool,
                "props_text": "Unregister pool; members fall back to global (must pair with Create)",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
                "fields": [{"key": "pool_name", "label": "Pool Name", "kind": "text"}],
            },
            {
                "type": "InitSigGenDevice", "label": "Init SigGen Device",
                "category": "SigGen", "color": sig,
                "props_text": "Create virtual sine source; device pin → AddToDevicePool (default: global)",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                    {"name": "device", "kind": "data", "direction": "output",
                     "data_type": "device", "optional": True},
                ],
                "fields": [
                    {"key": "device_name", "label": "Device", "kind": "text"},
                    {"key": "channels", "label": "Channels", "kind": "int", "default": 1, "min": 1, "max": 256},
                    {"key": "sampling_rate", "label": "Fs", "kind": "int", "default": 250, "min": 1, "max": 38400},
                    {"key": "frequency", "label": "F0", "kind": "float", "default": 10.0},
                    {"key": "freq_step", "label": "dF", "kind": "float", "default": 0.0},
                    {"key": "amplitude_uv", "label": "Amp", "kind": "float", "default": 100.0},
                    {"key": "noise_uv", "label": "Noise", "kind": "float", "default": 0.0},
                ],
            },
            {
                "type": "StartSigGenRecord", "label": "Start SigGen Record",
                "category": "SigGen", "color": sig,
                "props_text": "Begin synthesis into window buffer",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
                "fields": [{"key": "device_name", "label": "Device", "kind": "text"},
                           {"key": "pool", "label": "Pool", "kind": "text", "default": "global"}],
            },
            {
                "type": "StopSigGenRecord", "label": "Stop SigGen Record",
                "category": "SigGen", "color": sig,
                "props_text": "Stop synthesis + save to save_dir",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
                "fields": [{"key": "device_name", "label": "Device", "kind": "text"},
                           {"key": "pool", "label": "Pool", "kind": "text", "default": "global"},
                           {"key": "save_scope", "label": "Scope", "kind": "enum",
                            "choices": [["Session", "session"], ["Buffer", "buffer"]],
                            "default": "session"}],
            },
            {
                "type": "KillSigGenDevice", "label": "Kill SigGen Device",
                "category": "SigGen", "color": sig,
                "props_text": "Stop + close device (must pair with Init)",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
                "fields": [{"key": "device_name", "label": "Device", "kind": "text"},
                           {"key": "pool", "label": "Pool", "kind": "text", "default": "global"}],
            },
            {
                "type": "GetSigGenData", "label": "Get SigGen Data",
                "category": "SigGen", "color": sig,
                "props_text": "Copy of window buffer (channels x samples)",
                "pins": [
                    {"name": "Data", "kind": "data", "direction": "output", "data_type": "variant"},
                    {"name": "Channels", "kind": "data", "direction": "output", "data_type": "int"},
                    {"name": "Samples", "kind": "data", "direction": "output", "data_type": "int"},
                    {"name": "Fs", "kind": "data", "direction": "output", "data_type": "float"},
                ],
                "fields": [{"key": "device_name", "label": "Device", "kind": "text"},
                           {"key": "pool", "label": "Pool", "kind": "text", "default": "global"}],
            },
        ],
        "menu": [("Device", [
            ("SigGen", [
                ("Init SigGen Device", "InitSigGenDevice"),
                ("Start SigGen Record", "StartSigGenRecord"),
                ("Stop SigGen Record", "StopSigGenRecord"),
                ("Kill SigGen Device", "KillSigGenDevice"),
                ("Get SigGen Data", "GetSigGenData"),
            ]),
            ("Pool", [
                ("Create Device Pool", "CreateDevicePool"),
                ("Add To Device Pool", "AddToDevicePool"),
                ("Kill Device Pool", "KillDevicePool"),
            ]),
        ])],
    }
