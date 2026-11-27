#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :cli.py
@Description  :命令行模式 —— 无界面收发

**只 import core，绝不 import ui**：无 X 的机器上 import tkinter 就会失败，
而台架机 / SSH 环境正是这个模式的主要用途。

子命令：
    ports     列出可能的 ESP32 串口
    monitor   实时打印帧流
    send      发单帧
    cyc       周期发送（下发到固件本地调度）
    stat      读一次设备状态
    selftest  跑 core 层自测（等价 python -m BusSpyTool.tools.selftest）
"""
import argparse
import sys
import time
from typing import List, Optional

from BusSpyTool.config import app_meta
from BusSpyTool.core.bstp import Chn, Frame
from BusSpyTool.core.device import Device
from BusSpyTool.core.transport import SerialTransport

CHN_ALIASES = {"canfd": Chn.CANFD, "can": Chn.TWAI, "twai": Chn.TWAI,
               "eth": Chn.ETH}


def _parse_data(text: str) -> bytes:
    text = (text or "").replace(",", " ").strip()
    if not text:
        return b""
    parts = text.split()
    if len(parts) == 1 and len(parts[0]) > 2:
        return bytes.fromhex(parts[0])
    return bytes(int(p, 16) for p in parts)


def _build_device(args) -> Optional[Device]:
    if args.usb:
        return Device.over_usb(args.usb)
    if args.host:
        return Device.over_udp(args.host, args.port)
    ports = SerialTransport.list_candidates()
    if not ports:
        print("没有找到串口设备，用 --usb COM3 或 --host 192.168.1.50 指定", file=sys.stderr)
        return None
    print(f"自动选用 {ports[0][1]}")
    return Device.over_usb(ports[0][0])


def cmd_ports(_args) -> int:
    ports = SerialTransport.list_candidates()
    if not ports:
        print("没有检测到串口设备")
        return 1
    for device, text in ports:
        print(f"  {text}")
    return 0


def cmd_monitor(args) -> int:
    device = _build_device(args)
    if device is None:
        return 1
    count = [0]

    def on_frames(frames: List[Frame]):
        for frame in frames:
            count[0] += 1
            if args.limit and count[0] > args.limit:
                return
            print(f"{frame.ts_us / 1e6:12.4f}  chn{frame.chn}  "
                  f"{frame.direction}  {frame.id_text():>8}  "
                  f"[{len(frame.data):2d}]  {frame.data_text()}")

    device.add_listener(on_frames)
    if not device.connect():
        return 1
    print("监听中，Ctrl+C 退出")
    try:
        while True:
            if args.limit and count[0] >= args.limit:
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        device.disconnect()
    print(f"共收到 {count[0]} 帧")
    return 0


def cmd_send(args) -> int:
    device = _build_device(args)
    if device is None:
        return 1
    if not device.connect():
        return 1
    frame = Frame(can_id=int(args.id, 16), data=_parse_data(args.data),
                  chn=CHN_ALIASES.get(args.chn, Chn.CANFD),
                  fd=args.fd, brs=args.fd and not args.no_brs,
                  ide=args.ext, tx=True)
    ok = device.send_frame(frame)
    device.disconnect()
    print("已发送" if ok else "发送失败")
    return 0 if ok else 1


def cmd_cyc(args) -> int:
    device = _build_device(args)
    if device is None:
        return 1
    if not device.connect():
        return 1
    frame = Frame(can_id=int(args.id, 16), data=_parse_data(args.data),
                  chn=CHN_ALIASES.get(args.chn, Chn.CANFD),
                  fd=args.fd, brs=args.fd and not args.no_brs,
                  ide=args.ext, tx=True)
    slot = device.add_cyc(frame, int(args.period * 1000))
    print(f"周期槽 {slot} 已下发，周期 {args.period} ms（固件本地调度）")
    try:
        if args.duration:
            time.sleep(args.duration)
        else:
            print("Ctrl+C 停止")
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        device.remove_cyc(slot)
        device.disconnect()
    print("已停止")
    return 0


def cmd_stat(args) -> int:
    device = _build_device(args)
    if device is None:
        return 1
    if not device.connect():
        return 1
    time.sleep(1.5)        # 等一次 1 Hz 的 STAT
    stat = device.stat
    device.disconnect()
    print(f"运行时长      {stat.uptime_us / 1e6:,.1f} s")
    print(f"总线负载      {stat.bus_load_percent:.1f} %")
    print(f"错误状态      {stat.err_name}  TEC {stat.tec}  REC {stat.rec}")
    print(f"设备收/发     {stat.rx_frames:,} / {stat.tx_frames:,}")
    print(f"周期槽/miss   {stat.cyc_slots_active} / {stat.cyc_miss}")
    print(f"周期抖动 p99  {stat.jitter_p99_us} us")
    return 0


def cmd_selftest(_args) -> int:
    from BusSpyTool.tools.selftest import main as selftest_main
    return selftest_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="busspy",
        description=f"{app_meta.DEVICE_NAME} 命令行（无界面）")
    parser.add_argument("--version", action="version",
                        version=f"{app_meta.APP_NAME} "
                                f"{app_meta.host_version_text()}  "
                                f"(协议 {app_meta.PROTOCOL_NAME} "
                                f"v{app_meta.PROTOCOL_VERSION})")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--usb", help="串口，如 COM3 或 /dev/ttyACM0")
    common.add_argument("--host", help="设备 IP（走 UDP 时用）")
    common.add_argument("--port", type=int, default=8000, help="UDP 端口，默认 8000")

    frame_args = argparse.ArgumentParser(add_help=False)
    frame_args.add_argument("--id", required=True, help="CAN ID，十六进制")
    frame_args.add_argument("--data", default="", help="数据，十六进制，如 '00 11 22'")
    frame_args.add_argument("--chn", default="canfd",
                            choices=sorted(CHN_ALIASES), help="通道")
    frame_args.add_argument("--fd", action="store_true", help="CAN-FD 帧")
    frame_args.add_argument("--no-brs", action="store_true", help="FD 但不加速")
    frame_args.add_argument("--ext", action="store_true", help="扩展帧")

    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("ports", help="列出串口").set_defaults(func=cmd_ports)

    monitor = subs.add_parser("monitor", parents=[common], help="实时打印帧流")
    monitor.add_argument("--limit", type=int, default=0, help="收满多少帧后退出")
    monitor.set_defaults(func=cmd_monitor)

    send = subs.add_parser("send", parents=[common, frame_args], help="发单帧")
    send.set_defaults(func=cmd_send)

    cyc = subs.add_parser("cyc", parents=[common, frame_args], help="周期发送")
    cyc.add_argument("--period", type=float, required=True, help="周期，毫秒")
    cyc.add_argument("--duration", type=float, default=0, help="持续秒数，0 为一直")
    cyc.set_defaults(func=cmd_cyc)

    stat = subs.add_parser("stat", parents=[common], help="读设备状态")
    stat.set_defaults(func=cmd_stat)

    subs.add_parser("selftest", help="跑 core 层自测").set_defaults(func=cmd_selftest)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
