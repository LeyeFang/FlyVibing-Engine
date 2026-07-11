"""临时脚本 — SceneManager classmethod → 实例化 转换"""
import re

with open(r'Application\Core\Scene\SceneManager.py', encoding='utf-8') as f:
    content = f.read()

# 1. 删除 _SceneState 类定义
content = re.sub(
    r'class _SceneState:.*?(?=class SceneManager:)',
    '',
    content,
    flags=re.DOTALL
)

# 2. 更新类文档
content = content.replace(
    '场景管理器 — 每 Engine 独立的场景数据 + ECS 世界。\n\n    线程安全: 每个线程通过 set_thread_active() 绑定到特定 Engine。\n    同一 Engine 的多个线程共享同一个场景数据（但 ECS 世界切换是线程安全的关键）。',
    '场景管理器 — 每 Engine 一个实例，持有独立的 esper 世界。\n\n    实例化: scene = SceneManager("EditorHost", app)\n    线程: set_thread_active() 绑定线程到 engine (过渡期)'
)

# 3. 替换类级状态：_registry → _instances
old = '''    # ── 类级注册表 ─────────────────────────────────────────
    _registry: dict[str, _SceneState] = {}
    _active_name: str = ""                          # 全局默认 (线程本地未设置时的回落)
    _thread_active: dict[int, str] = {}             # thread_id → engine_name
    _thread_lock = threading.Lock()
    _component_registry: dict[str, type] = {}       # 组件注册表: name → Component class'''
new = '''    # ── 类级注册表 ─────────────────────────────────────────
    _instances: dict[str, 'SceneManager'] = {}       # engine_name → 实例
    _active_name: str = ""                          # 全局默认
    _thread_active: dict[int, str] = {}             # thread_id → engine_name
    _thread_lock = threading.Lock()
    _component_registry: dict[str, type] = {}       # 全局共享'''
content = content.replace(old, new)

# 4. 插入 __init__ + _create_default_cameras
init_code = '''
    def __init__(self, engine_name: str, app=None) -> None:
        from Application.Core.Scene.Scene import GameType
        self.engine_name = engine_name
        self.app = app
        self.scene: dict = {}
        self.entities: dict = {}
        self.scene_camera = None
        self.scene_camera_id: int | None = None
        self.main_camera_id: int | None = None
        self.main_camera_2d_id: int | None = None
        self._entity_names: dict[int, str] = {}
        self._entity_parent: dict[int, int] = {}
        self.world_name: str = f"scene_{engine_name}"
        self.game_type = GameType.GAME_3D
        SceneManager._instances[engine_name] = self
        esper.switch_world(self.world_name)
        self._create_default_cameras()
        if not SceneManager._component_registry:
            SceneManager._component_registry["Camera"] = Camera
            SceneManager._component_registry["MeshRenderer"] = MeshRenderer
            SceneManager._component_registry["Transform"] = Transform

    def _create_default_cameras(self) -> None:
        self.main_camera_id = esper.create_entity(
            Transform(position_x=0.0, position_y=0.0, position_z=10.0),
            Camera(True),
        )
        self.scene_camera_id = self.main_camera_id
        self.scene_camera = esper.component_for_entity(self.scene_camera_id, Camera)
        self.entities[f'{self.main_camera_id}'] = 1
        self._entity_names[self.main_camera_id] = "DefaultCamera3D"
        self.main_camera_2d_id = esper.create_entity(
            Transform(position_x=0.0, position_y=0.0, position_z=10.0, rotation_x=math.pi / 2.0),
            Camera(is_primary=False),
        )
        cam_2d = esper.component_for_entity(self.main_camera_2d_id, Camera)
        cam_2d.projection_type = ProjectionType.ORTHOGRAPHIC
        cam_2d.ortho_size = 10.0
        cam_2d.near_plane = 0.1
        cam_2d.far_plane = 100.0
        self.entities[f'{self.main_camera_2d_id}'] = 1
        self._entity_names[self.main_camera_2d_id] = "DefaultCamera2D"

    def _switch_world(self) -> None:
        esper.switch_world(self.world_name)
'''

insert_marker = '''    _component_registry: dict[str, type] = {}       # 全局共享'''
content = content.replace(insert_marker, insert_marker + init_code)

# 5. 转换方法: @classmethod → 普通方法, cls._state() → self._switch_world()

# 去掉所有 @classmethod 装饰器
content = re.sub(r'    @classmethod\n', '', content)

# cls._state() (独立调用) → self._switch_world()
content = content.replace('        cls._state()\n', '        self._switch_world()\n')

# st = cls._state() → 直接使用 self
content = content.replace('        st = cls._state()\n', '        self._switch_world()\n')

# return cls._state().xxx → self.xxx
content = re.sub(
    r'return cls\._state\(\)\.(\w+)',
    r'self._switch_world(); return self.\1',
    content
)

# st.xxx → self.xxx (在已经替换了 st = cls._state() 的方法中)
content = content.replace('        st.', '        self.')

# cls._state().app → self.app
content = content.replace('cls._state().app', 'self.app')

# 6. 重写 Init — 向后兼容 classmethod
old_init = '''    def Init(cls, app) -> None:
        """初始化场景 — 为当前 Engine 创建独立的场景状态 + ECS 世界。

        幂等：同一 Engine 多次调用不重复初始化。
        app 可以是 Engine 子类 (如 EditorHost) 或实例 (如 MockApp)。

        注意: Init() 不自动绑定线程 —— 调用方需通过 set_thread_active()
        将当前线程绑定到对应 Engine，确保多线程环境下 ECS 世界不串扰。
        """
        engine_name = getattr(app, '__name__', type(app).__name__)
        # 设置全局默认 (仅在没有线程本地时回落使用)
        if not cls._active_name:
            cls._active_name = engine_name

        if engine_name in cls._registry:
            cls._state().app = app
            return

        st = _SceneState()
        st.app = app
        st.scene["default"] = "default"
        st.world_name = f"scene_{engine_name}"
        cls._registry[engine_name] = st

        # ── 切换到本 Engine 的 ECS 世界（esper 自动创建）──
        esper.switch_world(st.world_name)

        # ── 3D 透视摄像机 ──
        # 编辑坐标 (0, -10, 0) → GL (0, 0, 10)
        # Camera.local_forward = (0, 0, -1) → 天然看向原点 (0, 0, 0)
        st.main_camera_id = esper.create_entity(
            Transform(position_x=0.0, position_y=0.0, position_z=10.0),
            Camera(True),
        )
        st.scene_camera_id = st.main_camera_id
        st.scene_camera = esper.component_for_entity(st.scene_camera_id, Camera)
        st.entities[f'{st.main_camera_id}'] = 1
        st._entity_names[st.main_camera_id] = "DefaultCamera3D"

        # ── 2D 正交俯视摄像机 ──
        st.main_camera_2d_id = esper.create_entity(
            Transform(
                position_x=0.0, position_y=0.0, position_z=10.0,
                rotation_x=math.pi / 2.0,
            ),
            Camera(is_primary=False),
        )
        cam_2d = esper.component_for_entity(st.main_camera_2d_id, Camera)
        cam_2d.projection_type = ProjectionType.ORTHOGRAPHIC
        cam_2d.ortho_size = 10.0
        cam_2d.near_plane = 0.1
        cam_2d.far_plane = 100.0
        st.entities[f'{st.main_camera_2d_id}'] = 1
        st._entity_names[st.main_camera_2d_id] = "DefaultCamera2D"

        # ── 首次 Init 时自动注册内置 Component ──
        if not cls._component_registry:
            cls.RegisterComponent("Camera", Camera)
            cls.RegisterComponent("MeshRenderer", MeshRenderer)
            cls.RegisterComponent("Transform", Transform)'''

new_init = '''    @classmethod
    def Init(cls, app) -> None:
        """[过渡期] 向后兼容 — 创建 SceneManager 实例。"""
        engine_name = getattr(app, '__name__', type(app).__name__)
        if not cls._active_name:
            cls._active_name = engine_name
        if engine_name in cls._instances:
            cls._instances[engine_name].app = app
            return
        SceneManager(engine_name, app)'''

content = content.replace(old_init, new_init)

# 7. 删除 _state() 和 _state_for() 旧实现，替换为新的
old_state = '''    @classmethod
    def _state(cls) -> _SceneState:
        """返回当前线程对应 Engine 的场景状态，并切换到对应的 esper 世界。"""
        name = cls._get_active_name()
        if name not in cls._registry:
            raise RuntimeError(
                f"SceneManager: no scene for engine '{name}'. "
                f"Call SceneManager.Init(engine) first."
            )
        st = cls._registry[name]
        esper.switch_world(st.world_name)
        return st

    @classmethod
    def _state_for(cls, engine_name: str) -> _SceneState:
        """返回指定 Engine 的场景状态（用于跨 Engine 操作）。"""
        return cls._registry[engine_name]'''

new_state = '''    @classmethod
    def _current(cls) -> 'SceneManager':
        """返回当前线程对应的 SceneManager 实例。"""
        name = cls._get_active_name()
        inst = cls._instances.get(name)
        if inst is None:
            raise RuntimeError(
                f"SceneManager: no instance for engine '{name}'. "
                f"Call SceneManager.Init(engine) first."
            )
        return inst

    @classmethod
    def _state_for(cls, engine_name: str) -> 'SceneManager':
        """返回指定 Engine 的 SceneManager 实例（跨 Engine 操作）。"""
        return cls._instances[engine_name]'''

content = content.replace(old_state, new_state)

# 8. 所有业务方法中，cls._state() → self 已经处理过了
#    但还有些方法调 cls._state_for(...) → 不需要改，还是 classmethod

# 9. 清理残留的 st. 引用（可能在 _apply_game_type_camera 等内部方法中）
#    这些方法接收 st 参数 → 改为接收 self, 或者直接访问 self

with open(r'Application\Core\Scene\SceneManager.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
