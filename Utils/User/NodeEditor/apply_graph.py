"""
apply_graph — 将节点图注入 scene 文件的 CLI 工具。

用法:
  # 从 JSON 文件注入
  python Utils/User/NodeEditor/apply_graph.py --scene MI.scene --graph graph.json

  # stdin 模式
  cat graph.json | python Utils/User/NodeEditor/apply_graph.py --scene MI.scene --stdin

  # 注入 + 验证
  python Utils/User/NodeEditor/apply_graph.py --scene MI.scene --graph graph.json --validate --frames 37000

  # 从 GraphBuilder 脚本注入
  python -c "from Utils.User.NodeEditor.graph_builder import GraphBuilder; ... ; g.save('MI.scene')"
"""

import argparse, json, os, sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def main():
    parser = argparse.ArgumentParser(description="Inject node graph into scene file")
    parser.add_argument("--scene", required=True, help="Path to .scene file")
    parser.add_argument("--graph", help="Path to graph JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read graph from stdin")
    parser.add_argument("--validate", action="store_true", help="Validate after injection")
    parser.add_argument("--frames", type=int, default=37000, help="Dry-run frames for validation")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # ── 读取 graph ──
    if args.stdin:
        graph = json.load(sys.stdin)
    elif args.graph:
        with open(args.graph, "r", encoding="utf-8") as f:
            graph = json.load(f)
    else:
        print("ERROR: --graph or --stdin required")
        sys.exit(1)

    # ── 写入 scene ──
    scene_path = args.scene
    if not os.path.isabs(scene_path):
        scene_path = os.path.join(_project_root, scene_path)
    if not os.path.exists(scene_path):
        print(f"ERROR: Scene file not found: {scene_path}")
        sys.exit(1)

    with open(scene_path, "r", encoding="utf-8") as f:
        scene_data = json.load(f)
    scene_data["scene"]["node_graph"] = graph
    with open(scene_path, "w", encoding="utf-8") as f:
        json.dump(scene_data, f, indent=2, ensure_ascii=False)
    print(f"[apply_graph] Injected: {len(graph.get('nodes',{}))} nodes, "
          f"{len(graph.get('links',{}))} links -> {scene_path}")

    # ── 验证 ──
    if args.validate:
        from Utils.User.NodeEditor.node_graph_validator import (
            validate_static, dry_run_simulation,
        )
        errors = validate_static(graph)
        if errors:
            print(f"\n  STATIC: {len(errors)} issue(s):")
            for e in errors:
                print(f"    - {e}")
        else:
            print("  STATIC: PASSED")

        if args.frames > 0:
            result = dry_run_simulation(
                graph, max_frames=args.frames, verbose=args.verbose)
            dr_errors = result.get("errors", [])
            if dr_errors:
                print(f"\n  DRY-RUN: {len(dr_errors)} issue(s):")
                for e in dr_errors:
                    print(f"    - {e}")
            else:
                print(f"  DRY-RUN: {result['frames_simulated']} frames, "
                      f"{result['total_events']} events")


if __name__ == "__main__":
    main()
