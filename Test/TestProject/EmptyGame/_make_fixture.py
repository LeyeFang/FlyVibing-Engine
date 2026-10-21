"""
EmptyGame fixture 生成器 — 重建空场景游戏测试夹具。

产出:
    scenes/Main.scene   — 零实体 + 默认三事件节点图 (OnGameStart/OnFrameUpdate/OnGameStop)
    EmptyGame.myproj    — 单场景工程, 无外部资源

运行:
    .venv-py314t\\Scripts\\python.exe Test/TestProject/EmptyGame/_make_fixture.py

⚠️ fixture 已提交到仓库; 仅在需要重建时运行本脚本。
"""

from __future__ import annotations

import json
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    scenes_dir = os.path.join(here, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)

    # ── 场景: 零实体 + 默认三节点图 ──
    from Application.Core.Scene.Scene import Scene, GameType
    from Application.Core.NodeGraph.canvas import NodeCanvas

    scene = Scene(name="Main")
    scene.game_type = GameType.GAME_3D
    canvas = NodeCanvas()
    canvas.create_default_nodes()
    scene.node_graph = canvas
    scene_path = os.path.join(scenes_dir, "Main.scene")
    scene.save_to_file(scene_path)
    print(f"[EmptyGame] written {scene_path}")

    # ── 工程: 单场景, 无资源 ──
    project = {
        "version": "0.1.0",
        "name": "EmptyGame",
        "startup_scene": "scenes\\Main.scene",
        "scenes": ["scenes\\Main.scene"],
        "resources": {
            "materials": [],
            "shaders": [],
            "textures": [],
            "meshes": [],
            "prefabs": [],
        },
    }
    proj_path = os.path.join(here, "EmptyGame.myproj")
    with open(proj_path, "w", encoding="utf-8") as fh:
        json.dump(project, fh, indent=2, ensure_ascii=False)
    print(f"[EmptyGame] written {proj_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
