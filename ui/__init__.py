#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
界面层（ttkbootstrap），只调用 core，不直接做 IO。

这里的工具函数都是 VehicleSimulate / McuVarTool 踩出来的跨平台坑，
照搬其做法，注释保留「为什么」——这些行为在两个平台上不对称，
改之前先看注释。
"""
import os
import sys
import tkinter

from BusSpyTool import paths
from BusSpyTool.utils.logger import logger


def set_app_user_model_id(app_id="qianli.BusSpyTool"):
    """给进程设置显式 AppUserModelID，否则 Windows 任务栏图标是空白的。

    任务栏按 AppUserModelID 分组并取图标，不认窗口的 wm_iconbitmap。不设的话
    Windows 会给宿主进程编一个隐式 ID，onedir 形态下取不到图标资源就显示空白方块。
    必须在建第一个窗口之前调用。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception as error:
        logger.debug("设置 AppUserModelID 失败（不影响使用）: %s", error)


def apply_window_icon(window):
    """给窗口设置程序图标。Tk 里每个 Toplevel 有独立图标，要逐个设。

    Windows 上要设两次：tkinter 的 wm_iconbitmap 只要给了 default 就会忽略
    位置参数，而 -default 只管「后续新建且没有自己图标」的窗口，不刷新本窗口
    标题栏。-default 只在根窗口上设，给 Toplevel 设会改掉全局默认图标。

    X11 上 Tk 的 iconbitmap 不认 .ico（要 XBM 格式），Ubuntu 上会静默失败，
    所以 Linux 走 iconphoto + PhotoImage(PNG)。
    """
    try:
        if sys.platform == "win32":
            icon = paths.icon_file()
            if os.path.isfile(icon):
                if isinstance(window, tkinter.Tk):
                    window.wm_iconbitmap(default=icon)
                window.wm_iconbitmap(icon)
            return
        png = paths.icon_png_file()
        if not os.path.isfile(png):
            return
        image = tkinter.PhotoImage(master=window, file=png)
        window.iconphoto(True, image)
        # PhotoImage 被回收后图标会掉，必须挂在窗口上留引用
        window._app_icon_image = image
    except Exception as error:
        logger.debug("设置窗口图标失败（不影响使用）: %s", error)


def enable_per_monitor_dpi():
    """建窗口前设 per-monitor v2 DPI 感知。

    ttkbootstrap 默认把进程设成 system DPI aware，多显示器下副屏会被 DWM
    位图缩放（文字糊）、主屏又按系统缩放折算（偏小）。必须在创建 Tk 实例
    之前调用才有效。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception as error:
            logger.debug("设置 DPI 感知失败（不影响使用）: %s", error)


def apply_titlebar_mode(window, dark: bool):
    """Windows 沉浸式深色标题栏。

    标题栏由 DWM 绘制，Tk 的主题管不到它 —— 不设的话深色主题下会留一条
    突兀的白边。属性号新版 20 / 旧版 19，两个都试。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                handle, attribute, ctypes.byref(value), ctypes.sizeof(value))
            if result == 0:
                break
    except Exception as error:
        logger.debug("设置标题栏配色失败（不影响使用）: %s", error)


def style_menus(menu, colors):
    """给经典 Tk 下拉菜单手动配色。

    下拉菜单是经典 Tk 控件，不吃 ttk 主题，切深色主题后不配色会是白底黑字。
    """
    try:
        menu.configure(
            background=colors.bg, foreground=colors.fg,
            activebackground=colors.primary, activeforeground=colors.selectfg,
            selectcolor=colors.fg, borderwidth=0, relief="flat")
    except Exception as error:
        logger.debug("菜单配色失败（不影响使用）: %s", error)


def show_centered(window, width=None, height=None):
    """先定位再显示，避免窗口从左上角闪到中心。

    不能用 ttkbootstrap 的 place_window_center()：它按 winfo_width() 算，
    withdraw 期间该值是 1，会偏半个窗口。这里用 reqwidth / 显式尺寸。
    """
    try:
        window.update_idletasks()
        width = width or window.winfo_reqwidth()
        height = height or window.winfo_reqheight()
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        window.geometry(f"{width}x{height}+{x}+{y}")
    except Exception as error:
        logger.debug("窗口居中失败（不影响使用）: %s", error)
    finally:
        # try/finally 保证搭界面出错时窗口也会显示，
        # 否则只剩一个看不见的进程
        window.deiconify()
