"""模拟状态机 — 统一管理 Run / Pause / Stop 状态"""
from enum import Enum, auto


class SimulationState(Enum):
    STOPPED = auto()
    RUNNING = auto()
    PAUSED = auto()


class SimulationController:
    """单例风格的模拟状态控制器 — 持有 GameRuntime 实例。"""

    _state: SimulationState = SimulationState.STOPPED

    # ── 状态查询 ────────────────────────────────────────────

    @classmethod
    def is_running(cls) -> bool:
        return cls._state == SimulationState.RUNNING

    @classmethod
    def is_paused(cls) -> bool:
        return cls._state == SimulationState.PAUSED

    @classmethod
    def is_stopped(cls) -> bool:
        return cls._state == SimulationState.STOPPED

    @classmethod
    def get_state(cls) -> SimulationState:
        return cls._state

    @classmethod
    def get_state_label(cls) -> str:
        if cls._state == SimulationState.RUNNING:
            return "Running"
        elif cls._state == SimulationState.PAUSED:
            return "Paused"
        else:
            return "Not running"

    # ── 状态变更 ────────────────────────────────────────────

    @classmethod
    def play(cls) -> None:
        """▶ 启动模拟 — 创建并启动 GameRuntime。"""
        from Application.Runtime.GameRuntime import GameRuntime
        from Application.Runtime.RuntimeLayer import RuntimeLayer

        if cls._state != SimulationState.STOPPED:
            return

        # 推入 RuntimeLayer 后启动
        GameRuntime.push_layer(RuntimeLayer)
        GameRuntime.start()
        cls._state = SimulationState.RUNNING
        print("[Simulation] Runtime started")

    @classmethod
    def pause(cls) -> None:
        """⏸ 暂停模拟（暂未实现）。"""
        if cls._state == SimulationState.RUNNING:
            cls._state = SimulationState.PAUSED

    @classmethod
    def resume(cls) -> None:
        """▶ 恢复运行（暂未实现）。"""
        if cls._state == SimulationState.PAUSED:
            cls._state = SimulationState.RUNNING

    @classmethod
    def stop(cls) -> None:
        """■ 停止模拟 — 停止 GameRuntime。"""
        from Application.Runtime.GameRuntime import GameRuntime

        if cls._state == SimulationState.STOPPED:
            return

        GameRuntime.stop()
        cls._state = SimulationState.STOPPED
        print("[Simulation] Runtime stopped")
