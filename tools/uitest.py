#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :uitest.py
@Description  :UI 冒烟测试 —— 真起窗口，自动连模拟设备，跑几秒后退出

不需要 ESP32 硬件。用途：
  - 验证界面能搭起来（布局异常会在这里崩，而不是到用户手上才崩）
  - 高帧率下的渲染回归（模拟器默认 400 帧/秒）
  - 出截图

跑法（在 platform_auto_test_tools 目录下）：
    python -m BusSpyTool.tools.uitest                 跑 5 秒后自动退出
    python -m BusSpyTool.tools.uitest --seconds 10
    python -m BusSpyTool.tools.uitest --shot out.png  跑完截图
    python -m BusSpyTool.tools.uitest --keep          不自动退出，手动看
"""
import argparse
import os
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description="BusSpyTool UI 冒烟测试")
    parser.add_argument("--seconds", type=float, default=5.0, help="运行秒数")
    parser.add_argument("--shot", help="截图保存路径（png）")
    parser.add_argument("--keep", action="store_true", help="不自动退出")
    parser.add_argument("--rate", type=int, default=400, help="模拟帧率")
    parser.add_argument("--tab", type=int, default=0, help="切到第几个页签")
    parser.add_argument("--dbc", nargs="*", default=None,
                        help="加载 DBC / ARXML，模拟流量会按它重建")
    parser.add_argument("--autograph", type=int, default=0,
                        help="自动往波形页加 N 条曲线")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    from BusSpyTool.ui import enable_per_monitor_dpi, set_app_user_model_id
    enable_per_monitor_dpi()
    set_app_user_model_id()

    from BusSpyTool.core.mock import MockDevice
    from BusSpyTool.ui.main_window import MainWindow

    window = MainWindow()
    window.title(window.title() + "   [冒烟测试 / 模拟设备]")

    device = MockDevice(frame_rate=args.rate)

    if args.dbc:
        for path in args.dbc:
            database = window.databases.add(path)
            if database.load_error:
                print(f"加载失败 {path}: {database.load_error}")
        window._reload_db_tree()
        messages = window.databases.all_messages()
        print(f"已加载 {len(window.databases)} 个数据库，{len(messages)} 条报文")
        # 必须在 connect 之前重建流量，否则 mock 的 ID 对不上数据库
        device.load_traffic(messages)
        if args.autograph:
            _fill_graph(window, messages, args.autograph)

    device.add_listener(window.buffer.extend)
    for callback in window._frame_listeners:
        device.add_listener(callback)
    device.connect()
    window.device = device
    window.connect_btn.configure(state="disabled")
    window.disconnect_btn.configure(state="normal")
    window.status_conn.configure(text="已连接  模拟设备", bootstyle="success")

    if args.tab:
        try:
            window.notebook.select(args.tab)
        except Exception:
            pass

    state = {"frames": 0, "ticks": 0}
    started = time.monotonic()

    def watchdog():
        state["ticks"] += 1
        state["frames"] = window.buffer.total_received
        elapsed = time.monotonic() - started
        if not args.keep and elapsed >= args.seconds:
            finish()
            return
        window.after(200, watchdog)

    def finish():
        if args.shot:
            _grab(window, args.shot)
        elapsed = time.monotonic() - started
        rate = state["frames"] / elapsed if elapsed else 0
        print(f"运行 {elapsed:.1f}s   收帧 {state['frames']:,} "
              f"（约 {rate:,.0f} 帧/秒）   UI tick {state['ticks']}")
        print(f"缓冲 {len(window.buffer):,}   聚合行 {len(window.buffer.aggregates())}")
        try:
            window._on_close()
        except Exception as error:
            print(f"关闭异常: {error}")

    window.after(300, watchdog)
    window.mainloop()
    return 0


def _fill_graph(window, messages, count):
    """给波形页塞几条曲线，否则截图是空白画布。

    挑有数值信号（非纯枚举、长度 > 1 位）的报文，曲线才有看头。
    """
    graph = window._pages.get("graph")
    if graph is None:
        return
    picks = []
    for info in messages:
        for signal in info.signals:
            if signal.length <= 1 or signal.choices:
                continue
            picks.append((info, signal))
            break
        if len(picks) >= count:
            break
    if picks:
        graph._add_series(picks)
        print(f"波形页已加入 {len(picks)} 条曲线")


def _grab(window, path):
    """截当前窗口。

    Windows / macOS 走系统截屏；Linux 必须给 ImageGrab 传 xdisplay，
    否则 Pillow 会去找 gnome-screenshot / scrot 这些外部工具，没装就失败。
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        print("缺少 Pillow，跳过截图")
        return
    try:
        window.update_idletasks()
        window.lift()
        window.update()
        time.sleep(0.4)
        x = window.winfo_rootx()
        y = window.winfo_rooty()
        box = (x, y, x + window.winfo_width(), y + window.winfo_height())
        kwargs = {}
        if sys.platform.startswith("linux"):
            kwargs["xdisplay"] = os.environ.get("DISPLAY", ":0")
        image = ImageGrab.grab(bbox=box, **kwargs)
        image.save(path)
        print(f"截图已保存 {path}  ({image.width}x{image.height})")
    except Exception as error:
        print(f"截图失败: {type(error).__name__}: {error}")


if __name__ == "__main__":
    sys.exit(main())
