"""
PlayerEntry — 无编辑器播放器入口（导出游戏 / 开发机播放）。

用法:
    python Application/PlayerEntry.py <game.json | 工程.myproj | 场景.scene>
        [--dry-run]      无头自检: 工程/资源/场景/节点图 + 静态校验 (+ --frames 假时间干跑)
        [--frames N]     干跑模式: 模拟 N 帧后结束;
                         运行模式: 真实运行 N 帧后自动退出（冒烟测试用）
        [--seconds T]    干跑: 绝对 fake-time 时长（秒; 覆盖 --frames）
        [--dt DT]        干跑: fake-time 步长（秒; 默认 1/60, 240Hz 用 0.0041666667）
        [--verbose]      干跑时逐节点打印执行追踪

退出码: 0=成功 / 1=运行错误 / 2=用法错误
"""

import os
import sys
import argparse
import traceback

# 确保工作区根目录在 sys.path 中（入口脚本在 Application/ 子目录下, 与 EntryPoint.py 同模式）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="PlayerEntry",
        description="FlyVibingEngine 无编辑器播放器",
    )
    parser.add_argument("source", help="入口: game.json / 工程 .myproj / 场景 .scene")
    parser.add_argument("--dry-run", action="store_true",
                        help="无头自检（不创建窗口）")
    parser.add_argument("--frames", type=int, default=0,
                        help="干跑: 模拟帧数; 运行: N 帧后自动退出（0=不限）")
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="干跑: 绝对 fake-time 时长（秒; 覆盖 --frames）")
    parser.add_argument("--dt", type=float, default=0.0,
                        help="干跑: fake-time 步长（秒; 默认 1/60, 240Hz 用 0.0041666667）")
    parser.add_argument("--verbose", action="store_true",
                        help="干跑逐节点追踪")
    args = parser.parse_args()

    from Application.Runtime import PlayerBootstrap

    if args.dry_run:
        dt = args.dt if args.dt > 0 else (1.0 / 60.0)
        frames = int(args.frames)
        if args.seconds > 0:
            frames = max(1, int(args.seconds / dt + 0.999999))
        return PlayerBootstrap.dry_run(
            args.source, frames=frames, verbose=args.verbose, dt=dt)
    return PlayerBootstrap.run(args.source, max_frames=args.frames)


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("\n[ERROR] Player exited with an unhandled exception")
        code = 1
    sys.exit(code)
