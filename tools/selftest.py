#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :selftest.py
@Description  :core 层自测，不需要硬件

跑法（在可导入 `BusSpyTool` 包的目录下）：
    python -m BusSpyTool.tools.selftest

覆盖 BSTP 编解码、批量切包、USB 流式重同步、DLC 映射、模拟设备。
这是 P1 之前唯一能做的回归，所以刻意做成零依赖、零硬件。
"""
import json
import os
import struct
import sys
import time

from BusSpyTool.core import bstp
from BusSpyTool.core.bstp import CHANNEL_NAMES, Chn, Frame, MsgType, Packet, Stat
from BusSpyTool.core.transport import SerialTransport

_failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [ok]   {name}")
    else:
        print(f"  [FAIL] {name}  {detail}")
        _failures.append(name)


def test_header():
    print("BSTP header")
    packet = Packet(MsgType.TX_FRAME, seq=0x1234, payload=b"\x01\x02")
    raw = packet.encode()
    check("header size is 12", bstp.HDR_SIZE == 12, f"got {bstp.HDR_SIZE}")
    check("magic is BSTP little-endian",
          raw[:4] == b"BSTP", f"got {raw[:4]!r}")
    check("magic constant matches",
          bstp.MAGIC == 0x50545342, f"got {bstp.MAGIC:#x}")
    back = Packet.decode(raw)
    check("round-trip msg_type", back.msg_type == MsgType.TX_FRAME)
    check("round-trip seq", back.seq == 0x1234)
    check("round-trip payload", back.payload == b"\x01\x02")

    try:
        Packet.decode(b"XXXX" + raw[4:])
        check("bad magic rejected", False, "no exception")
    except bstp.BstpError:
        check("bad magic rejected", True)


def test_channel_ids():
    print("stable channel IDs")
    check("legacy CAN-FD ID preserved", Chn.CANFD == 0)
    check("legacy TWAI ID preserved", Chn.TWAI == 1)
    check("legacy ETH ID preserved", Chn.ETH == 2)
    check("reserved CAN-FD ID appended", Chn.CANFD_2 == 3)
    check("reserved classic CAN IDs appended",
          (Chn.CAN_CLASSIC_2, Chn.CAN_CLASSIC_3) == (4, 5))
    ids = (Chn.CANFD_1, Chn.CAN_CLASSIC_1, Chn.ETH,
           Chn.CANFD_2, Chn.CAN_CLASSIC_2, Chn.CAN_CLASSIC_3)
    check("all endpoint IDs are unique", len(set(ids)) == Chn.ENDPOINT_COUNT)
    check("all endpoints have names", set(CHANNEL_NAMES) == set(ids))
    reserved_ids = (Chn.CAN_CLASSIC_1, Chn.ETH, Chn.CANFD_2,
                    Chn.CAN_CLASSIC_2, Chn.CAN_CLASSIC_3)
    check("all deferred endpoints are visibly reserved",
          all("预留" in CHANNEL_NAMES[channel_id]
              for channel_id in reserved_ids))
    from BusSpyTool.cli import CHN_ALIASES
    check("CLI aliases target reserved endpoints",
          CHN_ALIASES["canfd2"] == Chn.CANFD_2
          and CHN_ALIASES["can2"] == Chn.CAN_CLASSIC_2
          and CHN_ALIASES["can3"] == Chn.CAN_CLASSIC_3)


def test_dlc():
    print("DLC mapping")
    check("len 8 -> dlc 8", bstp.len_to_dlc(8) == 8)
    check("len 12 -> dlc 9", bstp.len_to_dlc(12) == 9)
    check("len 64 -> dlc 15", bstp.len_to_dlc(64) == 15)
    # CAN-FD 不允许 9 字节，必须向上取整到 12
    check("len 9 rounds up to 12", bstp.round_up_len(9) == 12)
    check("len 33 rounds up to 48", bstp.round_up_len(33) == 48)
    try:
        bstp.len_to_dlc(65)
        check("len 65 rejected", False, "no exception")
    except bstp.BstpError:
        check("len 65 rejected", True)


def test_frame():
    print("frame record")
    cases = [
        Frame(can_id=0x123, data=bytes(8), ts_us=1_000_000),
        Frame(can_id=0x1FFFFFFF, data=bytes(64), ide=True, fd=True, brs=True,
              ts_us=2_000_000, chn=Chn.CANFD),
        Frame(can_id=0x7FF, data=b"", ts_us=3),
        Frame(can_id=0x100, data=bytes(12), fd=True, tx=True, chn=Chn.TWAI),
        Frame(can_id=0x200, data=bytes(3), esi=True, rtr=True),
        Frame(can_id=0x301, data=bytes(8), fd=True, chn=Chn.CANFD_2),
        Frame(can_id=0x302, data=bytes(8), chn=Chn.CAN_CLASSIC_2),
        Frame(can_id=0x303, data=bytes(8), chn=Chn.CAN_CLASSIC_3),
    ]
    for index, original in enumerate(cases):
        blob = original.encode()
        check(f"case {index} wire_size matches encode",
              len(blob) == original.wire_size,
              f"{len(blob)} vs {original.wire_size}")
        check(f"case {index} 4-byte aligned", len(blob) % 4 == 0, f"{len(blob)}")
        back, offset = Frame.decode(memoryview(blob), 0)
        check(f"case {index} consumed all", offset == len(blob))
        same = (back.can_id == original.can_id and back.data == original.data
                and back.chn == original.chn and back.ts_us == original.ts_us
                and back.fd == original.fd and back.brs == original.brs
                and back.esi == original.esi and back.tx == original.tx
                and back.ide == original.ide and back.rtr == original.rtr)
        check(f"case {index} round-trip", same, f"{original} -> {back}")

    small = Frame(can_id=1, data=bytes(8))
    check("8-byte frame is 24 bytes on wire", small.wire_size == 24,
          f"got {small.wire_size}")


def test_batch():
    print("batch packing")
    frames = [Frame(can_id=0x100 + i, data=bytes(8), ts_us=i) for i in range(200)]
    packets = bstp.pack_frames(frames)
    check("split into multiple packets", len(packets) > 1, f"{len(packets)}")
    for packet in packets:
        check("each packet within MTU",
              len(packet.encode()) <= bstp.MTU_PAYLOAD,
              f"{len(packet.encode())}")
    recovered = []
    for packet in packets:
        recovered.extend(packet.frames())
    check("no frame lost", len(recovered) == len(frames),
          f"{len(recovered)} vs {len(frames)}")
    check("order preserved",
          all(r.can_id == o.can_id for r, o in zip(recovered, frames)))
    # 60 条 8 字节帧应装进一包
    check("60 small frames fit one packet",
          len(bstp.pack_frames(frames[:60])) == 1,
          f"{len(bstp.pack_frames(frames[:60]))}")


def test_stat():
    print("STAT record")
    original = Stat(uptime_us=123456789, rx_frames=10234, tx_frames=512,
                    rx_drop=1, tx_fail=2, cyc_slots_active=12, cyc_miss=0,
                    jitter_p99_us=41, bus_load_permille=372,
                    err_state=bstp.ErrState.PASSIVE, tec=8, rec=3,
                    link_up=True, wifi_up=False)
    back = Stat.decode(original.encode())
    check("round-trip uptime", back.uptime_us == original.uptime_us)
    check("round-trip rx_frames", back.rx_frames == original.rx_frames)
    check("round-trip cyc_miss", back.cyc_miss == original.cyc_miss)
    check("round-trip jitter", back.jitter_p99_us == original.jitter_p99_us)
    check("bus load percent", abs(back.bus_load_percent - 37.2) < 0.01,
          f"{back.bus_load_percent}")
    check("err name", back.err_name == "PASSIVE", back.err_name)
    check("link flags", back.link_up is True and back.wifi_up is False)


def test_cyc():
    print("CYC slot")
    frame = Frame(can_id=0x245, data=bytes(64), fd=True, brs=True)
    slot = bstp.CycSlot(3, frame, period_us=10_000, precise=True)
    blob = slot.encode()
    check("cyc header is 12 bytes", bstp.CYC_HDR_SIZE == 12,
          f"got {bstp.CYC_HDR_SIZE}")
    check("cyc header keeps frame 4-byte aligned", bstp.CYC_HDR_SIZE % 4 == 0)
    check("cyc blob length",
          len(blob) == bstp.CYC_HDR_SIZE + frame.wire_size,
          f"{len(blob)}")
    period, slot_id, e2e, precise, _, _ = struct.unpack_from(bstp.CYC_FMT, blob, 0)
    check("period encoded", period == 10_000, str(period))
    check("slot_id encoded", slot_id == 3, str(slot_id))
    check("precise encoded", precise == 1, str(precise))
    check("e2e default is none", e2e == 0xFFFF, hex(e2e))


def test_serial_resync():
    print("USB CDC stream resync")
    transport = SerialTransport("dummy")
    frames = [Frame(can_id=0x300 + i, data=bytes(8), ts_us=i) for i in range(5)]
    packets = bstp.pack_frames(frames, MsgType.RX_FRAME)
    stream = b"".join(p.encode() for p in packets)

    # 干净流
    transport._buf.extend(stream)
    out = transport._extract()
    check("clean stream parsed", len(out) == len(packets), f"{len(out)}")

    # 前面混入垃圾（固件 printf / 上电噪声）
    transport = SerialTransport("dummy")
    transport._buf.extend(b"boot garbage \xff\x00" + stream)
    out = transport._extract()
    check("garbage prefix skipped", len(out) == len(packets), f"{len(out)}")
    check("resync counted", transport.resync_bytes > 0,
          str(transport.resync_bytes))

    # 分片到达：逐字节喂也必须能还原
    transport = SerialTransport("dummy")
    collected = []
    for byte in stream:
        transport._buf.append(byte)
        collected.extend(transport._extract())
    check("byte-by-byte reassembly", len(collected) == len(packets),
          f"{len(collected)}")

    # 假 magic（长度字段离谱）后面跟真包
    transport = SerialTransport("dummy")
    fake = b"BSTP" + b"\x01\x90\x00\x00\xff\xff\x00\x00"
    transport._buf.extend(fake + stream)
    out = transport._extract()
    check("fake magic skipped, real packets kept", len(out) == len(packets),
          f"{len(out)}")

    # 没有 magic 时只保留末尾 3 字节，缓冲不无限增长
    transport = SerialTransport("dummy")
    transport._buf.extend(b"\x00" * 10000)
    transport._extract()
    check("buffer bounded without magic", len(transport._buf) <= 3,
          str(len(transport._buf)))


def test_mock_device():
    print("mock device")
    from BusSpyTool.core.mock import MockDevice
    device = MockDevice(frame_rate=200)
    received = []
    stats = []
    device.add_listener(lambda frames: received.extend(frames))
    device.add_stat_listener(stats.append)
    check("connect", device.connect() is True)
    time.sleep(1.3)
    device.disconnect()
    check("produced frames", len(received) > 50, f"{len(received)}")
    check("frames carry timestamps", all(f.ts_us >= 0 for f in received))
    check("emitted stat", len(stats) >= 1, f"{len(stats)}")
    check("stat has bus load", stats[0].bus_load_permille > 0 if stats else False)


def test_filter_and_ctrl():
    print("filter / ctrl packets")
    packet = bstp.filter_packet(0x123, Chn.CANFD, 1)
    check("filter msg_type", packet.msg_type == MsgType.FILTER_SET)
    check("filter payload is 8 bytes", len(packet.payload) == 8,
          str(len(packet.payload)))
    can_id, chn, action, _, _ = struct.unpack("<IBBBB", packet.payload)
    check("filter fields", can_id == 0x123 and chn == Chn.CANFD and action == 1)

    packet = bstp.ctrl_packet(bstp.Ctrl.BUS_ON)
    check("ctrl msg_type", packet.msg_type == MsgType.CTRL)
    command = struct.unpack_from("<BBH", packet.payload, 0)[0]
    check("ctrl command", command == bstp.Ctrl.BUS_ON)


def test_project():
    print("project file")
    import tempfile
    from BusSpyTool.core.project import Project

    with tempfile.TemporaryDirectory() as tmp:
        # 数据库放工程目录的子目录里 -> 应存成相对路径
        sub = os.path.join(tmp, "db")
        os.makedirs(sub, exist_ok=True)
        db_path = os.path.join(sub, "x.dbc")
        open(db_path, "w").close()

        project = Project(name="冒烟")
        project.path = os.path.join(tmp, "p.bsp")
        project.databases = [{"path": db_path, "channel": 0}]
        project.transmit = [{"name": "测试请求", "chn": 0, "id": "0x7E0",
                             "fd": True, "brs": True,
                             "data": "02 10 03", "period_ms": 0}]
        project.watch = [{"message": "M", "signal": "S"}]
        check("save", project.save() is True)

        raw = json.load(open(project.path, encoding="utf-8"))
        stored = raw["databases"][0]["path"]
        check("db path stored relative", stored == "db/x.dbc", stored)
        check("version written", raw["version"] == 1, str(raw.get("version")))

        back = Project.load(project.path)
        check("name round-trip", back.name == "冒烟", back.name)
        check("db path restored absolute",
              os.path.normcase(back.databases[0]["path"]) ==
              os.path.normcase(db_path), back.databases[0]["path"])
        check("transmit round-trip",
              back.transmit[0]["name"] == "测试请求", str(back.transmit[0]))
        check("watch round-trip", back.watch == project.watch)
        check("loaded project is clean", back.dirty is False)

        # 工程目录树之外 -> 保持绝对路径（否则会写出一串 ../../..）
        outside = os.path.abspath(os.path.join(tmp, "..", "outside.dbc"))
        project.databases = [{"path": outside, "channel": 1}]
        project.save()
        raw = json.load(open(project.path, encoding="utf-8"))
        check("outside path stays absolute",
              os.path.isabs(raw["databases"][0]["path"]),
              raw["databases"][0]["path"])

    # SendEntry 的配置往返（不依赖 tk，只测数据类）
    from BusSpyTool.ui.send_page import SendEntry
    entry = SendEntry.from_config({"name": "唤醒", "chn": 0, "id": "0x123",
                                   "fd": True, "brs": True, "ext": False,
                                   "data": "00 11 22", "period_ms": 10})
    check("SendEntry id parsed", entry.frame.can_id == 0x123,
          hex(entry.frame.can_id))
    check("SendEntry data parsed", entry.frame.data == b"\x00\x11\x22",
          repr(entry.frame.data))
    check("SendEntry period parsed", entry.period_ms == 10)
    again = SendEntry.from_config(entry.to_config())
    check("SendEntry round-trip",
          again.frame.can_id == entry.frame.can_id
          and again.frame.data == entry.frame.data
          and again.name == entry.name)


def main():
    print("=" * 56)
    print("BusSpyTool core selftest")
    print("=" * 56)
    for test in (test_header, test_channel_ids, test_dlc, test_frame, test_batch, test_stat,
                 test_cyc, test_serial_resync, test_filter_and_ctrl,
                 test_project, test_mock_device):
        test()
    print("=" * 56)
    if _failures:
        print(f"FAILED: {len(_failures)} check(s)")
        for name in _failures:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
