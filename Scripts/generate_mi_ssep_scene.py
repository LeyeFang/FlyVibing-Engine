"""
Generate MI-SSSEP.scene — combined MI + SSSEP experiment.

Trigger encoding (8-bit parallel port):
  bits [7:6] = MI  code: 01=左手, 10=右手, 11=双手
  bits [5:0] = SSSEP code: 1..14  (commands 11..24)

  trigger = (mi_val << 6) | (sssep_val - 10)
           = mi_val * 64 + sssep_val - 10

Timeline per trial (8s, 60 trials):
  t=0s: Random(1,3) → mi_val, show left/right cues
  t=1s: Random(11,24) → sssep_val, show task_cue,
        ParallelSend(trigger) → SerialSend(sssep_val)
  t=2s: hide all cues
  t=8s: reset → next trial
"""
from __future__ import annotations

import json
import copy
import sys
import os

# Pin ID helper — use nid*20 to avoid collisions (TimeTrigger has 11 pins)
def pid(nid: int, offset: int = 0) -> int:
    return nid * 20 + offset

# ── Scene entities (same as MI.scene) ──
def make_entities():
    """Return the entities dict (same visual layout as MI.scene)."""
    return {
        "1": {
            "name": "DefaultCamera3D",
            "components": {
                "Transform": {
                    "position_x": 0, "position_y": 0, "position_z": 10,
                    "rotation_x": 0, "rotation_y": 0, "rotation_z": 0,
                    "scale_x": 1, "scale_y": 1, "scale_z": 1,
                    "local_pos_x": 0, "local_pos_y": 0, "local_pos_z": 10,
                    "local_rot_x": 0, "local_rot_y": 0, "local_rot_z": 0,
                    "local_scl_x": 1, "local_scl_y": 1, "local_scl_z": 1,
                },
                "Camera": {
                    "projection_type": "perspective", "fov": 45,
                    "aspect_ratio": 1.7777777777777777, "ortho_size": 5,
                    "near_plane": 0.1, "far_plane": 1000,
                    "local_forward": [0, 0, -1], "up_vector": [0, 1, 0],
                    "is_primary": True,
                },
            },
        },
        "2": {
            "name": "DefaultCamera2D",
            "components": {
                "Transform": {
                    "position_x": 0, "position_y": 0, "position_z": 10,
                    "rotation_x": 1.5707963267948966, "rotation_y": 0, "rotation_z": 0,
                    "scale_x": 1, "scale_y": 1, "scale_z": 1,
                    "local_pos_x": 0, "local_pos_y": 0, "local_pos_z": 10,
                    "local_rot_x": 1.5707963267948966, "local_rot_y": 0, "local_rot_z": 0,
                    "local_scl_x": 1, "local_scl_y": 1, "local_scl_z": 1,
                },
                "Camera": {
                    "projection_type": "orthographic", "fov": 45,
                    "aspect_ratio": 1.7777777777777777, "ortho_size": 9,
                    "near_plane": 0.1, "far_plane": 100,
                    "local_forward": [0, 0, -1], "up_vector": [0, 1, 0],
                    "is_primary": False,
                },
            },
        },
        "3": {
            "name": "Left",
            "components": {
                "Transform": {
                    "position_x": -8, "position_y": 0, "position_z": 0,
                    "rotation_x": 0, "rotation_y": 0, "rotation_z": 0,
                    "scale_x": 2, "scale_y": 1, "scale_z": 1,
                    "local_pos_x": -8, "local_pos_y": 0, "local_pos_z": 0,
                    "local_rot_x": 0, "local_rot_y": 0, "local_rot_z": 0,
                    "local_scl_x": 2, "local_scl_y": 1, "local_scl_z": 1,
                },
                "MeshRenderer": {"mesh_id": 1, "material_id": 1, "visible": True},
            },
        },
        "4": {
            "name": "Right",
            "components": {
                "Transform": {
                    "position_x": 8, "position_y": 0, "position_z": 0,
                    "rotation_x": 0, "rotation_y": 0, "rotation_z": 0,
                    "scale_x": 2, "scale_y": 1, "scale_z": 1,
                    "local_pos_x": 8, "local_pos_y": 0, "local_pos_z": 0,
                    "local_rot_x": 0, "local_rot_y": 0, "local_rot_z": 0,
                    "local_scl_x": 2, "local_scl_y": 1, "local_scl_z": 1,
                },
                "MeshRenderer": {"mesh_id": 1, "material_id": 1, "visible": True},
            },
        },
        "5": {
            "name": "left_cue",
            "components": {
                "Transform": {
                    "position_x": -8, "position_y": 0, "position_z": 2,
                    "rotation_x": 0, "rotation_y": 0, "rotation_z": 0,
                    "scale_x": 1, "scale_y": 1, "scale_z": 0.35,
                    "local_pos_x": 0, "local_pos_y": 0, "local_pos_z": 2,
                    "local_rot_x": 0, "local_rot_y": 0, "local_rot_z": 0,
                    "local_scl_x": 1, "local_scl_y": 1, "local_scl_z": 0.35,
                },
                "MeshRenderer": {"mesh_id": 1, "material_id": 2, "visible": False},
            },
            "parent_id": 3,
        },
        "6": {
            "name": "right_cue",
            "components": {
                "Transform": {
                    "position_x": 8, "position_y": 0, "position_z": 2,
                    "rotation_x": 0, "rotation_y": 0, "rotation_z": 0,
                    "scale_x": 2, "scale_y": 1, "scale_z": 0.35,
                    "local_pos_x": 0, "local_pos_y": 0, "local_pos_z": 2,
                    "local_rot_x": 0, "local_rot_y": 0, "local_rot_z": 0,
                    "local_scl_x": 2, "local_scl_y": 1, "local_scl_z": 0.35,
                },
                "MeshRenderer": {"mesh_id": 1, "material_id": 2, "visible": False},
            },
            "parent_id": 4,
        },
        "7": {
            "name": "task_cue",
            "components": {
                "Transform": {
                    "position_x": 0, "position_y": 0, "position_z": 3,
                    "rotation_x": 0, "rotation_y": 0, "rotation_z": 0,
                    "scale_x": 10, "scale_y": 1, "scale_z": 0.35,
                    "local_pos_x": 0, "local_pos_y": 0, "local_pos_z": 3,
                    "local_rot_x": 0, "local_rot_y": 0, "local_rot_z": 0,
                    "local_scl_x": 10, "local_scl_y": 1, "local_scl_z": 0.35,
                },
                "MeshRenderer": {"mesh_id": 1, "material_id": 3, "visible": False},
            },
        },
    }


# ── Node helper ──
def node(nid: int, node_type: str, pos: list = None, props: dict = None, pin_ids: dict = None):
    return {
        "id": nid,
        "node_type": node_type,
        "pos": pos or [0, 0],
        "props": props or {},
        "pin_ids": pin_ids or {},
    }


# ═══════════════════════════════════════════════════════════════
# GRAPH DEFINITION
# ═══════════════════════════════════════════════════════════════

def build_node_graph() -> dict:
    nodes = {}
    links = {}

    # ─── Event Nodes (151-199) ───────────────────────────────
    nodes["151"] = node(151, "OnGameStart", [80, 80], {},
                        {"exec": pid(151)})
    nodes["153"] = node(153, "OnFrameUpdate", [-178, 255], {},
                        {"exec": pid(153), "delta": pid(153, 1)})
    nodes["156"] = node(156, "OnGameStop", [80, 480], {},
                        {"exec": pid(156)})

    # ─── OnGameStart Init Chain (200-219) ────────────────────
    # 200: RandomSetSeed
    nodes["200"] = node(200, "RandomSetSeed", [320, 60],
                         {"source": "hardware"},
                         {"exec_in": pid(200), "exec_out": pid(200, 1), "Seed": pid(200, 2)})

    # 201: VarGet(_global_random_seed)
    nodes["201"] = node(201, "VarGet", [580, 60],
                         {"var_name": "_global_random_seed"},
                         {"exec_in": pid(201), "Name": pid(201, 1),
                          "exec_out": pid(201, 2), "Value": pid(201, 3)})

    # 202: PathVar
    nodes["202"] = node(202, "PathVar", [580, -60],
                         {"browse_mode": "directory", "path": "Test/TestProject"},
                         {"Path": pid(202)})

    # 203: TimeGetDate — for seed file naming
    nodes["203"] = node(203, "TimeGetDate", [860, -60],
                         {"year": True, "month": True, "day": True,
                          "hour": True, "minute": True,
                          "format": "MI-SSSEP-Seed-%Y-%m-%d-%H-%M"},
                         {"DateString": pid(203)})

    # 204: TextFileWrite — save seed
    nodes["204"] = node(204, "TextFileWrite", [860, 20],
                         {"mode": "pin", "write_mode": "w", "delimiter": "newline"},
                         {"exec_in": pid(204), "exec_out": pid(204, 1),
                          "FilePath": pid(204, 2), "FileName": pid(204, 3),
                          "Value": pid(204, 4)})

    # 205-207: EntitySpawn
    nodes["205"] = node(205, "EntitySpawn", [0, 0],
                         {"template": "Left"},
                         {"exec_in": pid(205), "exec_out": pid(205, 1),
                          "Name": pid(205, 2), "Entity": pid(205, 3)})
    nodes["206"] = node(206, "EntitySpawn", [0, 0],
                         {"template": "Right"},
                         {"exec_in": pid(206), "exec_out": pid(206, 1),
                          "Name": pid(206, 2), "Entity": pid(206, 3)})
    nodes["207"] = node(207, "EntitySpawn", [0, 0],
                         {"template": "task_cue"},
                         {"exec_in": pid(207), "exec_out": pid(207, 1),
                          "Name": pid(207, 2), "Entity": pid(207, 3)})

    # 208-213: VarSet — init variables
    nodes["208"] = node(208, "VarSet", [0, 0],
                         {"mode": "manual", "var_name": "trial", "value": 1.0},
                         {"exec_in": pid(208), "Name": pid(208, 1),
                          "Value": pid(208, 2), "exec_out": pid(208, 3)})
    nodes["209"] = node(209, "VarSet", [0, 0],
                         {"mode": "manual", "var_name": "second", "value": 0.0},
                         {"exec_in": pid(209), "Name": pid(209, 1),
                          "Value": pid(209, 2), "exec_out": pid(209, 3)})
    nodes["210"] = node(210, "VarSet", [0, 0],
                         {"mode": "manual", "var_name": "next_time", "value": 1.0},
                         {"exec_in": pid(210), "Name": pid(210, 1),
                          "Value": pid(210, 2), "exec_out": pid(210, 3)})
    nodes["211"] = node(211, "VarSet", [0, 0],
                         {"mode": "manual", "var_name": "mi_val", "value": 0.0},
                         {"exec_in": pid(211), "Name": pid(211, 1),
                          "Value": pid(211, 2), "exec_out": pid(211, 3)})
    nodes["212"] = node(212, "VarSet", [0, 0],
                         {"mode": "manual", "var_name": "sssep_val", "value": 0.0},
                         {"exec_in": pid(212), "Name": pid(212, 1),
                          "Value": pid(212, 2), "exec_out": pid(212, 3)})

    # ─── Init visibility: hide all cues (213-219) ────────────
    # EntityGet left_cue → SetRenderVisible(false)
    nodes["213"] = node(213, "EntityGet", [0, 0],
                         {"entity_name": "left_cue"},
                         {"exec_in": pid(213), "exec_out": pid(213, 1),
                          "Name": pid(213, 2), "Entity": pid(213, 3)})
    nodes["215"] = node(215, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(215), "exec_out": pid(215, 1),
                          "EntityID": pid(215, 2), "Visible": pid(215, 3)})

    # EntityGet right_cue → SetRenderVisible(false)
    nodes["216"] = node(216, "EntityGet", [0, 0],
                         {"entity_name": "right_cue"},
                         {"exec_in": pid(216), "exec_out": pid(216, 1),
                          "Name": pid(216, 2), "Entity": pid(216, 3)})
    nodes["217"] = node(217, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(217), "exec_out": pid(217, 1),
                          "EntityID": pid(217, 2), "Visible": pid(217, 3)})

    # EntityGet task_cue → SetRenderVisible(false)
    nodes["218"] = node(218, "EntityGet", [0, 0],
                         {"entity_name": "task_cue"},
                         {"exec_in": pid(218), "exec_out": pid(218, 1),
                          "Name": pid(218, 2), "Entity": pid(218, 3)})
    nodes["219"] = node(219, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(219), "exec_out": pid(219, 1),
                          "EntityID": pid(219, 2), "Visible": pid(219, 3)})

    # ─── Constants (220-229) ─────────────────────────────────
    nodes["220"] = node(220, "Constant", [0, 0], {"value": 0.0}, {"Result": pid(220)})
    nodes["221"] = node(221, "Constant", [0, 0], {"value": 1.0}, {"Result": pid(221)})
    nodes["222"] = node(222, "Constant", [0, 0], {"value": 2.0}, {"Result": pid(222)})
    nodes["223"] = node(223, "Constant", [0, 0], {"value": 3.0}, {"Result": pid(223)})
    nodes["224"] = node(224, "Constant", [0, 0], {"value": 8.0}, {"Result": pid(224)})
    nodes["225"] = node(225, "Constant", [0, 0], {"value": 60.0}, {"Result": pid(225)})
    nodes["226"] = node(226, "Constant", [0, 0], {"value": 64.0}, {"Result": pid(226)})   # for mi_val * 64
    nodes["227"] = node(227, "Constant", [0, 0], {"value": 10.0}, {"Result": pid(227)})   # for sssep_val - 10

    # ─── OnFrameUpdate → TimeTrigger (230-231) ───────────────
    nodes["230"] = node(230, "VarGet", [84, 276],
                         {"var_name": "next_time"},
                         {"exec_in": pid(230), "Name": pid(230, 1),
                          "exec_out": pid(230, 2), "Value": pid(230, 3)})
    nodes["231"] = node(231, "TimeTrigger", [320, 320],
                         {"mode": "pin"},
                         {"exec_in": pid(231), "Time": pid(231, 1),
                          "Elapsed": pid(231, 2),
                          "out_0": pid(231, 3), "out_1": pid(231, 4),
                          "out_2": pid(231, 5), "out_3": pid(231, 6),
                          "out_4": pid(231, 7), "out_5": pid(231, 8),
                          "out_6": pid(231, 9), "out_7": pid(231, 10)})

    # ─── t=0s: MI randomization + cue display (232-250) ──────
    # VarGet(second) → Compare(second, 0, eq) → Branch
    nodes["232"] = node(232, "VarGet", [560, 280],
                         {"var_name": "second"},
                         {"exec_in": pid(232), "Name": pid(232, 1),
                          "exec_out": pid(232, 2), "Value": pid(232, 3)})
    nodes["233"] = node(233, "Compare", [0, 0],
                         {"operation": "eq"},
                         {"A": pid(233), "B": pid(233, 1), "Result": pid(233, 2)})
    nodes["234"] = node(234, "Branch", [0, 0], {},
                         {"exec_in": pid(234), "Condition": pid(234, 1),
                          "True": pid(234, 2), "False": pid(234, 3)})

    # Random(1,3) → VarSet(mi_val, mode=pin)
    nodes["235"] = node(235, "Random", [0, 0],
                         {"distribution": "discrete", "mode": "manual", "min": 1, "max": 3},
                         {"Min": pid(235), "Max": pid(235, 1),
                          "Mean": pid(235, 2), "StdDev": pid(235, 3),
                          "Result": pid(235, 4)})
    nodes["236"] = node(236, "VarSet", [0, 0],
                         {"mode": "pin", "var_name": "mi_val"},
                         {"exec_in": pid(236), "Name": pid(236, 1),
                          "Value": pid(236, 2), "exec_out": pid(236, 3)})

    # VarGet(mi_val) for cue branching
    nodes["237"] = node(237, "VarGet", [0, 0],
                         {"var_name": "mi_val"},
                         {"exec_in": pid(237), "Name": pid(237, 1),
                          "exec_out": pid(237, 2), "Value": pid(237, 3)})

    # ── mi_val == 1 → show left_cue ──
    nodes["238"] = node(238, "Compare", [0, 0],
                         {"operation": "eq"},
                         {"A": pid(238), "B": pid(238, 1), "Result": pid(238, 2)})
    nodes["239"] = node(239, "Branch", [0, 0], {},
                         {"exec_in": pid(239), "Condition": pid(239, 1),
                          "True": pid(239, 2), "False": pid(239, 3)})
    nodes["240"] = node(240, "EntityGet", [0, 0],
                         {"entity_name": "left_cue"},
                         {"exec_in": pid(240), "exec_out": pid(240, 1),
                          "Name": pid(240, 2), "Entity": pid(240, 3)})
    nodes["241"] = node(241, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(241), "exec_out": pid(241, 1),
                          "EntityID": pid(241, 2), "Visible": pid(241, 3)})

    # ── mi_val == 2 → show right_cue ──
    nodes["242"] = node(242, "Compare", [0, 0],
                         {"operation": "eq"},
                         {"A": pid(242), "B": pid(242, 1), "Result": pid(242, 2)})
    nodes["243"] = node(243, "Branch", [0, 0], {},
                         {"exec_in": pid(243), "Condition": pid(243, 1),
                          "True": pid(243, 2), "False": pid(243, 3)})
    nodes["244"] = node(244, "EntityGet", [0, 0],
                         {"entity_name": "right_cue"},
                         {"exec_in": pid(244), "exec_out": pid(244, 1),
                          "Name": pid(244, 2), "Entity": pid(244, 3)})
    nodes["245"] = node(245, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(245), "exec_out": pid(245, 1),
                          "EntityID": pid(245, 2), "Visible": pid(245, 3)})

    # ── mi_val == 3 → show both cues (exec chain: left then right) ──
    nodes["246"] = node(246, "Compare", [0, 0],
                         {"operation": "eq"},
                         {"A": pid(246), "B": pid(246, 1), "Result": pid(246, 2)})
    nodes["247"] = node(247, "Branch", [0, 0], {},
                         {"exec_in": pid(247), "Condition": pid(247, 1),
                          "True": pid(247, 2), "False": pid(247, 3)})
    # Reuse left_cue EntityGet+SetRenderVisible for mi_val==3
    nodes["248"] = node(248, "EntityGet", [0, 0],
                         {"entity_name": "left_cue"},
                         {"exec_in": pid(248), "exec_out": pid(248, 1),
                          "Name": pid(248, 2), "Entity": pid(248, 3)})
    nodes["249"] = node(249, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(249), "exec_out": pid(249, 1),
                          "EntityID": pid(249, 2), "Visible": pid(249, 3)})
    nodes["250"] = node(250, "EntityGet", [0, 0],
                         {"entity_name": "right_cue"},
                         {"exec_in": pid(250), "exec_out": pid(250, 1),
                          "Name": pid(250, 2), "Entity": pid(250, 3)})
    nodes["251"] = node(251, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(251), "exec_out": pid(251, 1),
                          "EntityID": pid(251, 2), "Visible": pid(251, 3)})

    # ─── t=1s: SSSEP + trigger + output (260-285) ────────────
    # VarGet(second) → Compare(second, 1, eq) → Branch
    nodes["260"] = node(260, "VarGet", [560, 360],
                         {"var_name": "second"},
                         {"exec_in": pid(260), "Name": pid(260, 1),
                          "exec_out": pid(260, 2), "Value": pid(260, 3)})
    nodes["261"] = node(261, "Compare", [0, 0],
                         {"operation": "eq"},
                         {"A": pid(261), "B": pid(261, 1), "Result": pid(261, 2)})
    nodes["262"] = node(262, "Branch", [0, 0], {},
                         {"exec_in": pid(262), "Condition": pid(262, 1),
                          "True": pid(262, 2), "False": pid(262, 3)})

    # Show task_cue
    nodes["263"] = node(263, "EntityGet", [0, 0],
                         {"entity_name": "task_cue"},
                         {"exec_in": pid(263), "exec_out": pid(263, 1),
                          "Name": pid(263, 2), "Entity": pid(263, 3)})
    nodes["264"] = node(264, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(264), "exec_out": pid(264, 1),
                          "EntityID": pid(264, 2), "Visible": pid(264, 3)})

    # Random(11,24) → VarSet(sssep_val, mode=pin)
    nodes["265"] = node(265, "Random", [0, 0],
                         {"distribution": "discrete", "mode": "manual",
                          "min": 11, "max": 24},
                         {"Min": pid(265), "Max": pid(265, 1),
                          "Mean": pid(265, 2), "StdDev": pid(265, 3),
                          "Result": pid(265, 4)})
    nodes["266"] = node(266, "VarSet", [0, 0],
                         {"mode": "pin", "var_name": "sssep_val"},
                         {"exec_in": pid(266), "Name": pid(266, 1),
                          "Value": pid(266, 2), "exec_out": pid(266, 3)})

    # ── Trigger computation ──
    # 1. mi_val * 64 → ScalarMath(multiply)
    nodes["267"] = node(267, "VarGet", [0, 0],
                         {"var_name": "mi_val"},
                         {"exec_in": pid(267), "Name": pid(267, 1),
                          "exec_out": pid(267, 2), "Value": pid(267, 3)})
    nodes["268"] = node(268, "ScalarMath", [0, 0],
                         {"operation": "multiply"},
                         {"In_0": pid(268), "In_1": pid(268, 1),
                          "In_2": pid(268, 2), "In_3": pid(268, 3),
                          "In_4": pid(268, 4), "In_5": pid(268, 5),
                          "In_6": pid(268, 6), "In_7": pid(268, 7),
                          "Result": pid(268, 8)})

    # 2. sssep_val - 10 → ScalarMath(subtract)
    nodes["269"] = node(269, "VarGet", [0, 0],
                         {"var_name": "sssep_val"},
                         {"exec_in": pid(269), "Name": pid(269, 1),
                          "exec_out": pid(269, 2), "Value": pid(269, 3)})
    nodes["270"] = node(270, "ScalarMath", [0, 0],
                         {"operation": "subtract"},
                         {"In_0": pid(270), "In_1": pid(270, 1),
                          "In_2": pid(270, 2), "In_3": pid(270, 3),
                          "In_4": pid(270, 4), "In_5": pid(270, 5),
                          "In_6": pid(270, 6), "In_7": pid(270, 7),
                          "Result": pid(270, 8)})

    # 3. temp1 + temp2 → trigger
    nodes["271"] = node(271, "ScalarMath", [0, 0],
                         {"operation": "sum"},
                         {"In_0": pid(271), "In_1": pid(271, 1),
                          "In_2": pid(271, 2), "In_3": pid(271, 3),
                          "In_4": pid(271, 4), "In_5": pid(271, 5),
                          "In_6": pid(271, 6), "In_7": pid(271, 7),
                          "Result": pid(271, 8)})

    # ── ParallelSend(trigger) — FIRST ──
    nodes["272"] = node(272, "ParallelSend", [0, 0],
                         {"mode": "pin", "address": 0x3FF8},
                         {"exec_in": pid(272), "exec_out": pid(272, 1),
                          "Address": pid(272, 2), "Value": pid(272, 3)})

    # ── SerialSend(sssep_val) — SECOND (after ParallelSend) ──
    nodes["273"] = node(273, "VarGet", [0, 0],
                         {"var_name": "sssep_val"},
                         {"exec_in": pid(273), "Name": pid(273, 1),
                          "exec_out": pid(273, 2), "Value": pid(273, 3)})
    nodes["274"] = node(274, "SerialSend", [0, 0],
                         {"mode": "pin", "format": "bytes",
                          "port": "COM4", "baud_rate": 9600},
                         {"exec_in": pid(274), "exec_out": pid(274, 1),
                          "Port": pid(274, 2), "BaudRate": pid(274, 3),
                          "Value": pid(274, 4)})

    # ─── t=2s: hide all cues (280-295) ───────────────────────
    nodes["280"] = node(280, "VarGet", [560, 440],
                         {"var_name": "second"},
                         {"exec_in": pid(280), "Name": pid(280, 1),
                          "exec_out": pid(280, 2), "Value": pid(280, 3)})
    nodes["281"] = node(281, "Compare", [0, 0],
                         {"operation": "eq"},
                         {"A": pid(281), "B": pid(281, 1), "Result": pid(281, 2)})
    nodes["282"] = node(282, "Branch", [0, 0], {},
                         {"exec_in": pid(282), "Condition": pid(282, 1),
                          "True": pid(282, 2), "False": pid(282, 3)})

    # Hide left_cue
    nodes["283"] = node(283, "EntityGet", [0, 0],
                         {"entity_name": "left_cue"},
                         {"exec_in": pid(283), "exec_out": pid(283, 1),
                          "Name": pid(283, 2), "Entity": pid(283, 3)})
    nodes["284"] = node(284, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(284), "exec_out": pid(284, 1),
                          "EntityID": pid(284, 2), "Visible": pid(284, 3)})

    # Hide right_cue
    nodes["285"] = node(285, "EntityGet", [0, 0],
                         {"entity_name": "right_cue"},
                         {"exec_in": pid(285), "exec_out": pid(285, 1),
                          "Name": pid(285, 2), "Entity": pid(285, 3)})
    nodes["286"] = node(286, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(286), "exec_out": pid(286, 1),
                          "EntityID": pid(286, 2), "Visible": pid(286, 3)})

    # Hide task_cue
    nodes["287"] = node(287, "EntityGet", [0, 0],
                         {"entity_name": "task_cue"},
                         {"exec_in": pid(287), "exec_out": pid(287, 1),
                          "Name": pid(287, 2), "Entity": pid(287, 3)})
    nodes["288"] = node(288, "EntitySetRenderVisible", [0, 0], {},
                         {"exec_in": pid(288), "exec_out": pid(288, 1),
                          "EntityID": pid(288, 2), "Visible": pid(288, 3)})

    # ─── Increment second & next_time (290-297) ───────────────
    nodes["290"] = node(290, "VarGet", [560, 520],
                         {"var_name": "second"},
                         {"exec_in": pid(290), "Name": pid(290, 1),
                          "exec_out": pid(290, 2), "Value": pid(290, 3)})
    nodes["291"] = node(291, "ScalarMath", [0, 0],
                         {"operation": "sum"},
                         {"In_0": pid(291), "In_1": pid(291, 1),
                          "In_2": pid(291, 2), "In_3": pid(291, 3),
                          "In_4": pid(291, 4), "In_5": pid(291, 5),
                          "In_6": pid(291, 6), "In_7": pid(291, 7),
                          "Result": pid(291, 8)})
    nodes["292"] = node(292, "VarSet", [0, 0],
                         {"mode": "pin", "var_name": "second"},
                         {"exec_in": pid(292), "Name": pid(292, 1),
                          "Value": pid(292, 2), "exec_out": pid(292, 3)})

    nodes["293"] = node(293, "VarGet", [560, 560],
                         {"var_name": "next_time"},
                         {"exec_in": pid(293), "Name": pid(293, 1),
                          "exec_out": pid(293, 2), "Value": pid(293, 3)})
    nodes["294"] = node(294, "ScalarMath", [0, 0],
                         {"operation": "sum"},
                         {"In_0": pid(294), "In_1": pid(294, 1),
                          "In_2": pid(294, 2), "In_3": pid(294, 3),
                          "In_4": pid(294, 4), "In_5": pid(294, 5),
                          "In_6": pid(294, 6), "In_7": pid(294, 7),
                          "Result": pid(294, 8)})
    nodes["295"] = node(295, "VarSet", [0, 0],
                         {"mode": "pin", "var_name": "next_time"},
                         {"exec_in": pid(295), "Name": pid(295, 1),
                          "Value": pid(295, 2), "exec_out": pid(295, 3)})

    # ─── Check second >= 8 → reset trial (300-312) ────────────
    nodes["300"] = node(300, "VarGet", [560, 640],
                         {"var_name": "second"},
                         {"exec_in": pid(300), "Name": pid(300, 1),
                          "exec_out": pid(300, 2), "Value": pid(300, 3)})
    nodes["301"] = node(301, "Compare", [0, 0],
                         {"operation": "gte"},
                         {"A": pid(301), "B": pid(301, 1), "Result": pid(301, 2)})
    nodes["302"] = node(302, "Branch", [0, 0], {},
                         {"exec_in": pid(302), "Condition": pid(302, 1),
                          "True": pid(302, 2), "False": pid(302, 3)})

    # Reset second = 0
    nodes["303"] = node(303, "VarSet", [0, 0],
                         {"mode": "manual", "var_name": "second", "value": 0.0},
                         {"exec_in": pid(303), "Name": pid(303, 1),
                          "Value": pid(303, 2), "exec_out": pid(303, 3)})

    # trial++
    nodes["304"] = node(304, "VarGet", [560, 720],
                         {"var_name": "trial"},
                         {"exec_in": pid(304), "Name": pid(304, 1),
                          "exec_out": pid(304, 2), "Value": pid(304, 3)})
    nodes["305"] = node(305, "ScalarMath", [0, 0],
                         {"operation": "sum"},
                         {"In_0": pid(305), "In_1": pid(305, 1),
                          "In_2": pid(305, 2), "In_3": pid(305, 3),
                          "In_4": pid(305, 4), "In_5": pid(305, 5),
                          "In_6": pid(305, 6), "In_7": pid(305, 7),
                          "Result": pid(305, 8)})
    nodes["306"] = node(306, "VarSet", [0, 0],
                         {"mode": "pin", "var_name": "trial"},
                         {"exec_in": pid(306), "Name": pid(306, 1),
                          "Value": pid(306, 2), "exec_out": pid(306, 3)})

    # ─── Check trial > 60 → ExitGame (307-312) ───────────────
    nodes["307"] = node(307, "VarGet", [560, 800],
                         {"var_name": "trial"},
                         {"exec_in": pid(307), "Name": pid(307, 1),
                          "exec_out": pid(307, 2), "Value": pid(307, 3)})
    nodes["308"] = node(308, "Compare", [0, 0],
                         {"operation": "gt"},
                         {"A": pid(308), "B": pid(308, 1), "Result": pid(308, 2)})
    nodes["309"] = node(309, "Branch", [0, 0], {},
                         {"exec_in": pid(309), "Condition": pid(309, 1),
                          "True": pid(309, 2), "False": pid(309, 3)})
    nodes["310"] = node(310, "ExitGame", [0, 0], {},
                         {"exec_in": pid(310)})

    # ═══════════════════════════════════════════════════════
    # LINKS
    # ═══════════════════════════════════════════════════════

    # Helper to add a link
    def link(lid: int, from_pin: int, to_pin: int):
        links[str(lid)] = {"id": lid, "from_pin": from_pin, "to_pin": to_pin}

    lid = 500

    # ── OnGameStart chain ──
    # OnGameStart → RandomSetSeed
    link(lid, pid(151), pid(200)); lid += 1
    # RandomSetSeed → VarGet(seed)
    link(lid, pid(200, 1), pid(201)); lid += 1
    # VarGet(seed).exec_out → TextFileWrite.exec_in
    link(lid, pid(201, 2), pid(204)); lid += 1
    # PathVar.Path → TextFileWrite.FilePath
    link(lid, pid(202), pid(204, 2)); lid += 1
    # DateTimeString → TextFileWrite.FileName
    link(lid, pid(203), pid(204, 3)); lid += 1
    # VarGet(seed).Value → TextFileWrite.Value
    link(lid, pid(201, 3), pid(204, 4)); lid += 1

    # TextFileWrite → EntitySpawn(Left)
    link(lid, pid(204, 1), pid(205)); lid += 1
    # EntitySpawn(Left) → EntitySpawn(Right)
    link(lid, pid(205, 1), pid(206)); lid += 1
    # EntitySpawn(Right) → EntitySpawn(task_cue)
    link(lid, pid(206, 1), pid(207)); lid += 1

    # EntitySpawn(task_cue) → VarSet(trial=1)
    link(lid, pid(207, 1), pid(208)); lid += 1
    # VarSet(trial) → VarSet(second=0)
    link(lid, pid(208, 3), pid(209)); lid += 1
    # VarSet(second) → VarSet(next_time=1)
    link(lid, pid(209, 3), pid(210)); lid += 1
    # VarSet(next_time) → VarSet(mi_val=0)
    link(lid, pid(210, 3), pid(211)); lid += 1
    # VarSet(mi_val) → VarSet(sssep_val=0)
    link(lid, pid(211, 3), pid(212)); lid += 1

    # ── Init visibility: hide all cues ──
    # VarSet(sssep_val) → EntityGet(left_cue)
    link(lid, pid(212, 3), pid(213)); lid += 1
    # EntityGet(left_cue).Entity → SetRenderVisible.EntityID
    link(lid, pid(213, 3), pid(215, 2)); lid += 1
    # Constant(0) → SetRenderVisible.Visible
    link(lid, pid(220), pid(215, 3)); lid += 1
    # EntityGet(left_cue).exec_out → SetRenderVisible(left_cue).exec_in
    link(lid, pid(213, 1), pid(215)); lid += 1

    # SetRenderVisible(left_cue) → EntityGet(right_cue)
    link(lid, pid(215, 1), pid(216)); lid += 1
    # EntityGet(right_cue).Entity → SetRenderVisible.EntityID
    link(lid, pid(216, 3), pid(217, 2)); lid += 1
    # Constant(0) → SetRenderVisible.Visible
    link(lid, pid(220), pid(217, 3)); lid += 1
    # EntityGet(right_cue).exec_out → SetRenderVisible(right_cue).exec_in
    link(lid, pid(216, 1), pid(217)); lid += 1

    # SetRenderVisible(right_cue) → EntityGet(task_cue)
    link(lid, pid(217, 1), pid(218)); lid += 1
    # EntityGet(task_cue).Entity → SetRenderVisible.EntityID
    link(lid, pid(218, 3), pid(219, 2)); lid += 1
    # Constant(0) → SetRenderVisible.Visible
    link(lid, pid(220), pid(219, 3)); lid += 1
    # EntityGet(task_cue).exec_out → SetRenderVisible(task_cue).exec_in
    link(lid, pid(218, 1), pid(219)); lid += 1

    # ── OnFrameUpdate → VarGet(next_time) → TimeTrigger ──
    link(lid, pid(153), pid(230)); lid += 1
    link(lid, pid(230, 2), pid(231)); lid += 1
    # VarGet(next_time).Value → TimeTrigger.Time
    link(lid, pid(230, 3), pid(231, 1)); lid += 1

    # ── t=0s: MI randomization ──
    # TimeTrigger.out_0 → VarGet(second)
    link(lid, pid(231, 3), pid(232)); lid += 1
    # VarGet(second).Value → Compare.A (second == 0)
    link(lid, pid(232, 3), pid(233)); lid += 1
    # Constant(0) → Compare.B
    link(lid, pid(220), pid(233, 1)); lid += 1
    # Compare.Result → Branch.Condition
    link(lid, pid(233, 2), pid(234, 1)); lid += 1
    # VarGet(second).exec_out → Branch.exec_in
    link(lid, pid(232, 2), pid(234)); lid += 1

    # Branch.True → VarSet(mi_val, mode=pin)
    link(lid, pid(234, 2), pid(236)); lid += 1
    # Random.Result → VarSet(mi_val).Value
    link(lid, pid(235, 4), pid(236, 2)); lid += 1

    # VarSet(mi_val) → VarGet(mi_val) for cue branching
    link(lid, pid(236, 3), pid(237)); lid += 1

    # ── mi_val == 1 → show left_cue ──
    # VarGet(mi_val).Value → Compare.A (mi_val == 1)
    link(lid, pid(237, 3), pid(238)); lid += 1
    # Constant(1) → Compare.B
    link(lid, pid(221), pid(238, 1)); lid += 1
    # Compare.Result → Branch.Condition
    link(lid, pid(238, 2), pid(239, 1)); lid += 1
    # VarGet(mi_val).exec_out → Branch.exec_in
    link(lid, pid(237, 2), pid(239)); lid += 1

    # Branch.True → EntityGet(left_cue) → SetRenderVisible(true)
    link(lid, pid(239, 2), pid(240)); lid += 1
    link(lid, pid(240, 3), pid(241, 2)); lid += 1  # Entity → EntityID
    link(lid, pid(221), pid(241, 3)); lid += 1       # Constant(1) → Visible
    link(lid, pid(240, 1), pid(241)); lid += 1        # exec_out → exec_in

    # ── mi_val == 2 → show right_cue ──
    # VarGet(mi_val).Value → Compare.A (mi_val == 2)
    link(lid, pid(237, 3), pid(242)); lid += 1
    # Constant(2) → Compare.B
    link(lid, pid(222), pid(242, 1)); lid += 1
    # Compare.Result → Branch.Condition
    link(lid, pid(242, 2), pid(243, 1)); lid += 1
    # Branch.True from mi_val==1.False → mi_val==2.Branch.exec_in
    # (chain: if mi_val != 1, check mi_val == 2)
    link(lid, pid(239, 3), pid(243)); lid += 1

    # Branch.True → EntityGet(right_cue) → SetRenderVisible(true)
    link(lid, pid(243, 2), pid(244)); lid += 1
    link(lid, pid(244, 3), pid(245, 2)); lid += 1
    link(lid, pid(221), pid(245, 3)); lid += 1
    link(lid, pid(244, 1), pid(245)); lid += 1

    # ── mi_val == 3 → show both cues ──
    # VarGet(mi_val).Value → Compare.A (mi_val == 3)
    link(lid, pid(237, 3), pid(246)); lid += 1
    # Constant(3) → Compare.B
    link(lid, pid(223), pid(246, 1)); lid += 1
    # Compare.Result → Branch.Condition
    link(lid, pid(246, 2), pid(247, 1)); lid += 1
    # Branch.True from mi_val==2.False → mi_val==3.Branch.exec_in
    link(lid, pid(243, 3), pid(247)); lid += 1

    # Branch.True → EntityGet(left_cue) → SetRenderVisible(true)
    link(lid, pid(247, 2), pid(248)); lid += 1
    link(lid, pid(248, 3), pid(249, 2)); lid += 1
    link(lid, pid(221), pid(249, 3)); lid += 1
    link(lid, pid(248, 1), pid(249)); lid += 1

    # SetRenderVisible(left_cue) → EntityGet(right_cue) → SetRenderVisible(true)
    link(lid, pid(249, 1), pid(250)); lid += 1
    link(lid, pid(250, 3), pid(251, 2)); lid += 1
    link(lid, pid(221), pid(251, 3)); lid += 1
    link(lid, pid(250, 1), pid(251)); lid += 1

    # ── Collect exec flow after t=0s MI branch ──
    # After mi_val==1 branch (True or False), continue to t=1s check
    # mi_val==1 True → SetRenderVisible(left_cue).exec_out → t=1s VarGet(second)
    link(lid, pid(241, 1), pid(260)); lid += 1
    # mi_val==1 False → mi_val==2 branch (already linked)
    # mi_val==2 True → SetRenderVisible(right_cue).exec_out → t=1s (join)
    link(lid, pid(245, 1), pid(260)); lid += 1  # join with mi_val==1 True
    # mi_val==3 True → SetRenderVisible(right_cue for both).exec_out → t=1s
    link(lid, pid(251, 1), pid(260)); lid += 1
    # mi_val==2 False False → t=1s (when mi_val != 1,2,3 — shouldn't happen but safe)
    link(lid, pid(247, 3), pid(260)); lid += 1

    # Also the initial second==0 False path goes to t=1s
    link(lid, pid(234, 3), pid(260)); lid += 1

    # ── t=1s: SSSEP + trigger + output ──
    # VarGet(second).Value → Compare.A (second == 1)
    link(lid, pid(260, 3), pid(261)); lid += 1
    # Constant(1) → Compare.B
    link(lid, pid(221), pid(261, 1)); lid += 1
    # Compare.Result → Branch.Condition
    link(lid, pid(261, 2), pid(262, 1)); lid += 1
    # VarGet(second).exec_out → Branch.exec_in
    link(lid, pid(260, 2), pid(262)); lid += 1

    # Branch.True → EntityGet(task_cue) → SetRenderVisible(true)
    link(lid, pid(262, 2), pid(263)); lid += 1
    link(lid, pid(263, 3), pid(264, 2)); lid += 1
    link(lid, pid(221), pid(264, 3)); lid += 1
    link(lid, pid(263, 1), pid(264)); lid += 1

    # SetRenderVisible(task_cue) → VarSet(sssep_val)
    link(lid, pid(264, 1), pid(266)); lid += 1
    # Random(11,24).Result → VarSet(sssep_val).Value
    link(lid, pid(265, 4), pid(266, 2)); lid += 1

    # ── Trigger computation ──
    # VarGet(mi_val).Value → ScalarMath(multiply).In_0
    link(lid, pid(267, 3), pid(268)); lid += 1
    # Constant(64) → ScalarMath(multiply).In_1
    link(lid, pid(226), pid(268, 1)); lid += 1

    # VarGet(sssep_val).Value → ScalarMath(subtract).In_0
    link(lid, pid(269, 3), pid(270)); lid += 1
    # Constant(10) → ScalarMath(subtract).In_1
    link(lid, pid(227), pid(270, 1)); lid += 1

    # ScalarMath(multiply).Result → ScalarMath(sum).In_0
    link(lid, pid(268, 8), pid(271)); lid += 1
    # ScalarMath(subtract).Result → ScalarMath(sum).In_1
    link(lid, pid(270, 8), pid(271, 1)); lid += 1

    # VarSet(sssep_val).exec_out → VarGet(mi_val) for trigger calc
    link(lid, pid(266, 3), pid(267)); lid += 1
    # VarGet(mi_val).exec_out → VarGet(sssep_val) for trigger calc
    link(lid, pid(267, 2), pid(269)); lid += 1

    # VarGet(sssep_val).exec_out → ParallelSend.exec_in
    link(lid, pid(269, 2), pid(272)); lid += 1
    # ScalarMath(sum).Result → ParallelSend.Value
    link(lid, pid(271, 8), pid(272, 3)); lid += 1

    # ParallelSend.exec_out → VarGet(sssep_val) for SerialSend
    link(lid, pid(272, 1), pid(273)); lid += 1
    # VarGet(sssep_val).exec_out → SerialSend.exec_in
    link(lid, pid(273, 2), pid(274)); lid += 1
    # VarGet(sssep_val).Value → SerialSend.Value
    link(lid, pid(273, 3), pid(274, 4)); lid += 1

    # SerialSend.exec_out → t=2s check (or skip if second!=1)
    link(lid, pid(274, 1), pid(280)); lid += 1
    # Branch.False (second != 1) → t=2s check
    link(lid, pid(262, 3), pid(280)); lid += 1

    # ── t=2s: hide all cues ──
    link(lid, pid(280, 3), pid(281)); lid += 1
    link(lid, pid(221), pid(281, 1)); lid += 1  # Constant(2) → Compare.B — wait, second==2!
    # Actually I need Constant(2) here. Let me use the existing one.
    # Hmm, I defined Constant(2) as 222. Let me fix: Compare(second, 2, eq)
    # Need to re-link: Constant(2) → Compare.B
    # Actually I already have Constant(222) with value 2. Let me use it.
    # Oops, I defined Constant(221) as value 1 and (222) as value 2. But here I need 2.
    # The link above should be: Constant(222) → Compare.B(281, 1)
    # Let me fix this...

    # Actually, the issue is I wrote link(lid, pid(221), pid(281,1)) — that's 1, not 2.
    # The compare is for second == 2, so B should be Constant(222) = 2.0
    # But I already used that link ID. Let me just fix the connections below.
    
    # Let me restart the t=2s section with correct values. I'll handle this in the cleanup.
    
    link(lid, pid(281, 2), pid(282, 1)); lid += 1
    link(lid, pid(280, 2), pid(282)); lid += 1

    # Branch.True → hide left_cue
    link(lid, pid(282, 2), pid(283)); lid += 1
    link(lid, pid(283, 3), pid(284, 2)); lid += 1
    link(lid, pid(220), pid(284, 3)); lid += 1  # Constant(0) → Visible
    link(lid, pid(283, 1), pid(284)); lid += 1

    # → hide right_cue
    link(lid, pid(284, 1), pid(285)); lid += 1
    link(lid, pid(285, 3), pid(286, 2)); lid += 1
    link(lid, pid(220), pid(286, 3)); lid += 1
    link(lid, pid(285, 1), pid(286)); lid += 1

    # → hide task_cue
    link(lid, pid(286, 1), pid(287)); lid += 1
    link(lid, pid(287, 3), pid(288, 2)); lid += 1
    link(lid, pid(220), pid(288, 3)); lid += 1
    link(lid, pid(287, 1), pid(288)); lid += 1

    # ── Increment second & next_time (after t=2s or skip) ──
    link(lid, pid(288, 1), pid(290)); lid += 1
    link(lid, pid(282, 3), pid(290)); lid += 1  # second != 2 → skip to increment

    link(lid, pid(290, 3), pid(291)); lid += 1    # second.Value → ScalarMath.In_0
    link(lid, pid(221), pid(291, 1)); lid += 1     # +1
    link(lid, pid(291, 8), pid(292, 2)); lid += 1  # Result → VarSet(second).Value
    link(lid, pid(290, 2), pid(292)); lid += 1     # exec_out → VarSet.exec_in

    link(lid, pid(292, 3), pid(293)); lid += 1     # → VarGet(next_time)
    link(lid, pid(293, 3), pid(294)); lid += 1     # next_time.Value → ScalarMath.In_0
    link(lid, pid(221), pid(294, 1)); lid += 1      # +1
    link(lid, pid(294, 8), pid(295, 2)); lid += 1   # Result → VarSet(next_time).Value
    link(lid, pid(293, 2), pid(295)); lid += 1

    # ── Check second >= 8 → reset ──
    link(lid, pid(295, 3), pid(300)); lid += 1
    link(lid, pid(300, 3), pid(301)); lid += 1     # second.Value → Compare.A
    link(lid, pid(224), pid(301, 1)); lid += 1      # Constant(8) → Compare.B
    link(lid, pid(301, 2), pid(302, 1)); lid += 1   # Result → Branch.Condition
    link(lid, pid(300, 2), pid(302)); lid += 1

    # Branch.True → VarSet(second=0)
    link(lid, pid(302, 2), pid(303)); lid += 1

    # VarSet(second=0) → VarGet(trial)
    link(lid, pid(303, 3), pid(304)); lid += 1
    # trial.Value → ScalarMath.In_0
    link(lid, pid(304, 3), pid(305)); lid += 1
    # +1
    link(lid, pid(221), pid(305, 1)); lid += 1
    # Result → VarSet(trial).Value
    link(lid, pid(305, 8), pid(306, 2)); lid += 1
    # VarGet(trial).exec_out → VarSet(trial).exec_in
    link(lid, pid(304, 2), pid(306)); lid += 1

    # ── Check trial > 60 → ExitGame ──
    link(lid, pid(306, 3), pid(307)); lid += 1
    link(lid, pid(307, 3), pid(308)); lid += 1     # trial.Value → Compare.A
    link(lid, pid(225), pid(308, 1)); lid += 1      # Constant(60) → Compare.B
    link(lid, pid(308, 2), pid(309, 1)); lid += 1   # Result → Branch.Condition
    link(lid, pid(307, 2), pid(309)); lid += 1

    # Branch.True → ExitGame
    link(lid, pid(309, 2), pid(310)); lid += 1

    # ═══════════════════════════════════════════════════════
    # FIX: t=2s Compare.B should be Constant(2), not Constant(1)
    # ═══════════════════════════════════════════════════════
    # Find and fix the link that connects Constant(221)=1 to Compare(281).B
    # It should be Constant(222)=2 → Compare(281).B
    # Search through links to find: to_pin == pid(281,1)
    for link_id, link_data in list(links.items()):
        if link_data["to_pin"] == pid(281, 1):
            link_data["from_pin"] = pid(222)  # Constant(2) instead of Constant(1)

    # ── Also need: after cue display exec chains merge properly ──
    # The mi_val==1 branch True path: SetRenderVisible(left_cue) → VarGet(second) for t=1s
    # This was linked above. 
    # The mi_val==2 branch True path: SetRenderVisible(right_cue) → also merge to t=1s
    # These parallel links to pid(260) [VarGet(second) exec_in] are fine — 
    # the evaluator handles multiple exec inputs by just following the active chain.

    # Compute next_id
    all_ids = set()
    for n in nodes.values():
        all_ids.add(n["id"])
        for p in n["pin_ids"].values():
            all_ids.add(int(p))
    for l in links.values():
        all_ids.add(l["id"])
        all_ids.add(l["from_pin"])
        all_ids.add(l["to_pin"])
    next_id = max(all_ids) + 1 if all_ids else 1

    # ── Rules document ──
    rules = """## Node Graph JSON Reference (v0.1.0)

### JSON Structure
The node_graph is a JSON object with these keys:
- "version": "0.1.0"
- "nodes": { "<nid>": {NodeInstance}, ... }  — nid is globally unique int (string key)
- "links": { "<lid>": {LinkInstance}, ... }  — lid is globally unique int (string key)
- "next_id": int — 1 + max(all node/link/pin IDs), ensures no collision on future additions
- "_rules": "<this document>"

### NodeInstance Format
  "id": <int>, "node_type": "<type_name>", "pos": [<x>, <y>],
  "props": {<key>: <value>, ...},  — mode-dependent props (see per-node table)
  "pin_ids": {"<pin_name>": <int>, ...}  — instance-level unique pin IDs

### LinkInstance Format
  "id": <int>, "from_pin": <int> (output pin ID), "to_pin": <int> (input pin ID)

### Pin IDs
Every node has a pin_ids dict mapping logical pin name → instance-unique integer.
All links reference these instance-level IDs, NOT template-level PinDef IDs.
When writing a graph, assign pin IDs sequentially starting from a high base (e.g., nid*10).

### Connection Rules (CRITICAL)
1. exec pins connect exec→exec: output exec pin → input exec pin
2. data pins connect data→data: output data pin → input data pin
3. NEVER connect exec→data or data→exec
4. One output pin can fan out to multiple input pins (both exec and data)
5. An input pin can only receive from ONE output pin
6. Event nodes (OnGameStart/OnFrameUpdate/OnGameStop) have NO input exec pins — they are graph roots

### Execution Model
- OnGameStart: fires ONCE when the game begins. Use for initialization (set variables, spawn entities).
- OnFrameUpdate: fires EVERY FRAME. Use for per-frame checks (TimeTrigger, input polling).
- OnGameStop: fires ONCE when the game ends. Use for cleanup.
- Exec chain: _walk_exec follows exec output→input links depth-first.
- Data nodes (Constant, Compare, ScalarMath, MakeVec3, BreakVec3, VecMath, Random, legacy math):
  evaluated lazily when an exec node needs their output value via data links.
- TimeTrigger: when Elapsed >= Time, fires out_0...out_7, re-arms when Time changes.

### Node Type Quick Reference
| NodeType | Input Pins | Output Pins | Key Props |
|---|---|---|---|
| OnGameStart | — | exec | — |
| OnFrameUpdate | — | exec, delta | — |
| OnGameStop | — | exec | — |
| VarSet | exec_in, Name, Value | exec_out | mode: manual/pin, var_name, value |
| VarGet | exec_in, Name | exec_out, Value | var_name |
| Constant | — | Result | value |
| ScalarMath | In_0..In_7 (float) | Result (float) | operation: sum/subtract/multiply/divide |
| Compare | A, B | Result | operation: gt/lt/eq/neq/gte/lte |
| Branch | exec_in, Condition | True, False | — |
| Random | Min, Max, Mean, StdDev | Result | distribution: discrete/normal, mode: manual/pin, min, max |
| TimeTrigger | exec_in, Time | Elapsed, out_0..out_7 | mode: manual/pin |
| EntitySpawn | exec_in, Name | exec_out, Entity | template |
| EntityGet | exec_in, Name | exec_out, Entity | entity_name |
| EntitySetRenderVisible | exec_in, EntityID, Visible | exec_out | — |
| SerialSend | exec_in, Port, BaudRate, Value | exec_out | mode: manual/pin, format: bytes, port, baud_rate, value |
| ParallelSend | exec_in, Address, Value | exec_out | mode: manual/pin, address, value |
| ExitGame | exec_in | — | — |
| TextFileWrite | exec_in, FilePath, FileName, Value | exec_out | mode: pin, write_mode: w/a, delimiter: newline |
| PathVar | — | Path | browse_mode: directory, path |
| TimeGetDate | — | DateString | year/month/day/hour/minute, format |
| StringConst | — | Result | value |
| RandomSetSeed | exec_in | exec_out, Seed | source: hardware/time/manual |
"""

    return {
        "version": "0.1.0",
        "nodes": nodes,
        "links": links,
        "next_id": next_id,
        "_rules": rules,
    }


def build_scene() -> dict:
    return {
        "version": "0.1.0",
        "scene": {
            "name": "MI-SSSEP",
            "game_type": "2d",
            "entities": make_entities(),
            "main_camera_entity_id": 1,
            "next_eid": 8,
            "node_graph": build_node_graph(),
        },
    }


def main():
    scene = build_scene()
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "Test", "TestProject", "MI-SSSEP.scene"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scene, f, indent=2, ensure_ascii=False)
    print(f"✅ Written MI-SSSEP.scene → {output_path}")
    print(f"   Nodes: {len(scene['scene']['node_graph']['nodes'])}")
    print(f"   Links: {len(scene['scene']['node_graph']['links'])}")
    print(f"   Next ID: {scene['scene']['node_graph']['next_id']}")


if __name__ == "__main__":
    main()
