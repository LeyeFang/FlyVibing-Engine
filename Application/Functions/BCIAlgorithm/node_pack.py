"""BCI node pack — FBCSP / CCA / Epoch 数据集节点（2026-10-20 从核心迁出）。

节点声明与 `Core/NodeGraph/node_types` 解耦；type 名保持不变。
求值器仍由现有 BCI/epoch 域实现提供，后续由 BCI 维护者收回本目录。
本文件必须是纯声明（不 import Editor / imgui）。
"""

from __future__ import annotations


def register() -> dict:
    algo = (0.600, 0.360, 0.720)
    epoch = (0.290, 0.680, 0.600)
    return {
        "id": "bci",
        "name": "BCI Algorithm",
        "owner": "bci",
        "nodes": [
            {
                "type": "InitFBCSP", "label": "Init FBCSP", "category": "Algorithm", "color": algo,
                "props_text": "Register FBCSP spec (n_components / classifier / bands [+]) — bands empty = plain CSP",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
            },
            {
                "type": "TrainFBCSP", "label": "Train FBCSP", "category": "Algorithm", "color": algo,
                "props_text": "Train (blocks until done) or load a model; keep on a repeatedly-triggered chain",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
            },
            {
                "type": "TestFBCSP", "label": "Test FBCSP", "category": "Algorithm", "color": algo,
                "props_text": "Signal in → Label out (trained model by model_name)",
                "pins": [
                    {"name": "Data", "kind": "data", "direction": "input", "data_type": "variant"},
                    {"name": "Samples", "kind": "data", "direction": "input", "data_type": "int"},
                    {"name": "Label", "kind": "data", "direction": "output", "data_type": "int"},
                    {"name": "Confidence", "kind": "data", "direction": "output", "data_type": "float"},
                ],
            },
            {
                "type": "TestCCA", "label": "Test CCA", "category": "Algorithm", "color": algo,
                "props_text": "CCA (training-free): Data+Fs → Label(idx)/Score/Freq — freq groups [+], >=2",
                "pins": [
                    {"name": "Data", "kind": "data", "direction": "input", "data_type": "variant"},
                    {"name": "Samples", "kind": "data", "direction": "input", "data_type": "int"},
                    {"name": "Fs", "kind": "data", "direction": "input", "data_type": "float"},
                    {"name": "Label", "kind": "data", "direction": "output", "data_type": "int"},
                    {"name": "Score", "kind": "data", "direction": "output", "data_type": "float"},
                    {"name": "Freq", "kind": "data", "direction": "output", "data_type": "float"},
                ],
            },
            {
                "type": "EpochAppend", "label": "Append Epoch", "category": "Epoch", "color": epoch,
                "props_text": "Append one epoch (channels x samples) + label — link Get*Data outputs",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                    {"name": "Data", "kind": "data", "direction": "input", "data_type": "variant"},
                    {"name": "Samples", "kind": "data", "direction": "input", "data_type": "int"},
                    {"name": "Fs", "kind": "data", "direction": "input", "data_type": "float"},
                    {"name": "Label", "kind": "data", "direction": "input", "data_type": "float"},
                ],
            },
            {
                "type": "EpochCount", "label": "Count Epochs", "category": "Epoch", "color": epoch,
                "props_text": "Dataset stats — gate training with Count (pure data node)",
                "pins": [
                    {"name": "Count", "kind": "data", "direction": "output", "data_type": "int"},
                    {"name": "Classes", "kind": "data", "direction": "output", "data_type": "int"},
                    {"name": "Channels", "kind": "data", "direction": "output", "data_type": "int"},
                    {"name": "Fs", "kind": "data", "direction": "output", "data_type": "float"},
                ],
            },
            {
                "type": "EpochClear", "label": "Clear Epochs", "category": "Epoch", "color": epoch,
                "props_text": "Clear a dataset (idempotent)",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
            },
            {
                "type": "EpochSave", "label": "Save Epoch Dataset", "category": "Epoch", "color": epoch,
                "props_text": "Save dataset as npz — dry-run computes path only",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
            },
            {
                "type": "EpochLoad", "label": "Load Epoch Dataset", "category": "Epoch", "color": epoch,
                "props_text": "Load dataset from npz (mode: replace/append)",
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                ],
            },
        ],
        "menu": [("BCI", [
            ("Epoch", [
                ("Append Epoch", "EpochAppend"),
                ("Count Epochs", "EpochCount"),
                ("Clear Epochs", "EpochClear"),
                ("Save Epoch Dataset", "EpochSave"),
                ("Load Epoch Dataset", "EpochLoad"),
            ]),
            ("Algorithm", [
                ("Init FBCSP", "InitFBCSP"),
                ("Train FBCSP", "TrainFBCSP"),
                ("Test FBCSP", "TestFBCSP"),
                ("Test CCA", "TestCCA"),
            ]),
        ])],
    }
