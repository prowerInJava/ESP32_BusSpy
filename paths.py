#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :paths.py
@Description  :包内路径解析的唯一出口

各层模块散落在 core/ ui/ config/ utils/ 里，深度不同，谁都不该自己
用 os.path.dirname(__file__) 往上数层级——挪一次文件就会错一次。
统一从这里取，并在这里处理 PyInstaller 打包后的 sys._MEIPASS。

沿用桌面应用常见的资源路径处理方式（见 writable_dir / icon_png_file）。
"""
import os
import sys

PACKAGE_NAME = "BusSpyTool"
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))


def resource_root():
    """只读资源的根目录。

    打包后资源被解到 sys._MEIPASS/BusSpyTool（见 tools/build_exe.py 的
    --add-data 目标路径），源码运行时就是包目录本身。
    """
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        bundled = os.path.join(bundle_dir, PACKAGE_NAME)
        if os.path.isdir(bundled):
            return bundled
        return bundle_dir
    return PACKAGE_ROOT


def data_dir():
    """随包只读数据（图标、CHANGELOG、波特率表）。"""
    return os.path.join(resource_root(), "data")


_writable_dir_cache = None


def _probe_writable(directory):
    """真去建目录写个探针文件——Windows 下 os.access 对 ACL 判断不可靠。"""
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, ".write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def writable_dir():
    """要写入的目录（日志 / 偏好 / ASC trace）。

    打包后优先用 exe 所在目录（便于运维就地看日志）；但 exe 可能被放到
    Program Files 或只读共享里，那里建不了目录会让程序在 --windowed 下
    静默崩掉，所以不可写时回落到 %LOCALAPPDATA%\\BusSpyTool。
    """
    global _writable_dir_cache
    if _writable_dir_cache:
        return _writable_dir_cache

    if getattr(sys, "frozen", False):
        candidates = [
            os.path.dirname(os.path.abspath(sys.executable)),
            os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), PACKAGE_NAME),
        ]
    else:
        candidates = [PACKAGE_ROOT]

    for candidate in candidates:
        if _probe_writable(candidate):
            _writable_dir_cache = candidate
            return candidate
    _writable_dir_cache = candidates[-1]
    return _writable_dir_cache


def log_dir():
    return os.path.join(writable_dir(), "log")


def settings_file():
    return os.path.join(writable_dir(), "settings.json")


def trace_dir():
    """ASC trace 落盘目录。固件不存 trace，录制一律在上位机侧。"""
    return os.path.join(writable_dir(), "trace")


def version_info_file():
    return os.path.join(resource_root(), "version_info.txt")


def icon_file():
    """Windows 用的 .ico 图标。随包资源，打包后在 _MEIPASS 下。"""
    return os.path.join(data_dir(), "app.ico")


def icon_png_file():
    """Linux 用的 PNG 图标：X11 上 Tk 的 iconbitmap 不认 .ico（要 XBM），
    只能用 iconphoto + PhotoImage(PNG)。"""
    return os.path.join(data_dir(), "app.png")


def changelog_file():
    return os.path.join(data_dir(), "CHANGELOG.md")
