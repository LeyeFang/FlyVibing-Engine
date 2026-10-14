# Utils.Dev — 引擎开发与打包工具链（开发者专用，不随产品分发）
#
#   setup_env.bat      一键开发者环境（uv + Python 3.14t + .venv-py314t）
#   rebuild_lock.bat   维护者：重生成 uv-py314t.lock
#   collect_wheels.py  重建 wheelhouse（Resource/wheels，从 PyPI）
#   prepare_runtime.py 预制运行时镜像（Resource/runtime，安装器/导出游戏共用）
#   Installer/         安装包构建（Inno Setup）
#
# [计划] build_tools.py — 发布入口: 一次产出 ExtDev 全部 wheel + CHECKSUMS
#        （Doc/Dev/ecosystem_plan.md §2「发布脚本」）
