#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :app.py
@Description  :启动入口（薄壳）

不带参数开界面，**带参数走命令行**（cli.py）。同一个可执行文件兼两种用法，
无显示器的台架机 / 纯 SSH 也能发报文。

ui 的 import 必须放在函数内：无 X 的机器上 import tkinter 会直接失败，
命令行分支不该被它拖累。
"""
import os
import sys


def _ensure_path():
    """直接 python app.py 跑时，把仓库根加进 sys.path。

    打包后 PyInstaller 自己处理依赖，这段不会生效也不需要生效。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if root not in sys.path:
        sys.path.insert(0, root)


def main():
    _ensure_path()

    argv = sys.argv[1:]
    # --project xxx.bsp 仍然是开界面，不是命令行模式
    project = None
    if argv and argv[0] in ("--project", "-p") and len(argv) >= 2:
        project = argv[1]
        argv = argv[2:]

    if argv:
        from BusSpyTool.cli import main as cli_main
        return cli_main(sys.argv[1:])

    # 必须在建第一个窗口之前设，否则任务栏图标空白 / 副屏文字发虚
    from BusSpyTool.ui import enable_per_monitor_dpi, set_app_user_model_id
    enable_per_monitor_dpi()
    set_app_user_model_id()

    from BusSpyTool.ui.main_window import MainWindow
    window = MainWindow()
    window.open_project_on_start(project)
    window.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
