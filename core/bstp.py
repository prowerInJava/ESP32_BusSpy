#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :bstp.py
@Description  :BSTP v1 (Bus Spy Tool Protocol) 编解码

与 ESP32-BusSpyTool 固件的线上格式，规格见
docs/DESIGN.md 第 2.3 节。

设计要点（相对旧版 UDP 协议的改进）：
  - 12 字节定长头带 magic + version + msg_type，不再靠包长度裸分发
  - 一个 UDP 包可装多帧（批量），减少短帧传输开销
  - 帧记录的 len 是**实际字节数**，不是 DLC code
  - seq 可做请求/响应配对与丢包检测

全协议小端：ESP32-S3 与 x86_64 都是小端，零字节序转换。
纯标准库，不 import ui，可在无 X 的台架机上用。
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

MAGIC = 0x50545342          # "BSTP" 小端
VERSION = 1

HDR_FMT = "<IBBHHBB"
HDR_SIZE = struct.calcsize(HDR_FMT)        # 12

FRAME_FMT = "<QIBBBB"
FRAME_HDR_SIZE = struct.calcsize(FRAME_FMT)  # 16

CYC_FMT = "<IHHBBH"                         # period_us, slot_id, e2e_idx, precise, rsv8, rsv16
CYC_HDR_SIZE = struct.calcsize(CYC_FMT)      # 12 —— 必须凑到 4 的倍数，
                                             # 否则紧跟其后的 frame record 里的
                                             # u64 ts_us 在 Xtensa 上不对齐

STAT_FMT = "<QIIIIIIIHBBBBB"

# UDP payload 上限：MTU 1500 - 20(IP) - 8(UDP)
MTU_PAYLOAD = 1472
MAX_BATCH_PAYLOAD = MTU_PAYLOAD - HDR_SIZE

# CAN-FD 合法数据长度。索引即 DLC code，值为字节数。
DLC_TO_LEN = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)


class MsgType:
    HELLO = 0x01
    CFG_SET = 0x02
    TX_FRAME = 0x10
    CYC_SET = 0x11
    FILTER_SET = 0x12
    CTRL = 0x13
    HELLO_ACK = 0x81
    CFG_ACK = 0x82
    RX_FRAME = 0x90
    STAT = 0x91
    ERROR = 0x9F


class Ctrl:
    START = 1
    STOP = 2
    RESET = 3
    BUS_ON = 4
    BUS_OFF = 5
    CYC_START = 6
    CYC_STOP = 7
    WIFI_ON = 8
    WIFI_OFF = 9
    E2E_FAULT = 10


class Chn:
    CANFD = 0        # MCP2518FD
    TWAI = 1         # ESP32-S3 内置，CAN 2.0 预留通道
    ETH = 2          # arxml 裸 UDP 帧


class ErrState:
    ACTIVE = 0
    WARN = 1
    PASSIVE = 2
    BUSOFF = 3

    NAMES = ("ACTIVE", "WARN", "PASSIVE", "BUSOFF")

    @classmethod
    def name(cls, value):
        return cls.NAMES[value] if 0 <= value < len(cls.NAMES) else f"?{value}"


# ---- 帧标志位 ----
F_FD = 0x01
F_BRS = 0x02
F_ESI = 0x04
F_TX = 0x08

# ---- can_id 标志位 ----
ID_MASK = 0x1FFFFFFF
ID_ERR = 1 << 29
ID_RTR = 1 << 30
ID_IDE = 1 << 31


class BstpError(ValueError):
    """BSTP 解析失败。调用方应丢弃该 UDP 包并计数，不要尝试部分解析。"""


def len_to_dlc(length: int) -> int:
    """字节数 -> DLC code。

    CAN-FD 只允许 DLC_TO_LEN 里那些长度，9/10/11 这种要向上取整到 12 并补 0。
    非法长度（负数或 >64）直接抛错，不静默截断——静默会把配置错误藏到现场。
    """
    if not 0 <= length <= 64:
        raise BstpError(f"illegal CAN payload length {length}")
    for code, size in enumerate(DLC_TO_LEN):
        if size >= length:
            return code
    raise BstpError(f"illegal CAN payload length {length}")


def round_up_len(length: int) -> int:
    """字节数向上取整到合法的 CAN-FD 长度。"""
    return DLC_TO_LEN[len_to_dlc(length)]


def _pad4(n: int) -> int:
    return (4 - (n & 3)) & 3


@dataclass
class Frame:
    """一条 CAN / CAN-FD / 裸 UDP 帧。

    ts_us 对 RX 是固件侧 MCP2518FD 硬件 TBC 打的时间戳（微秒），
    对 TX 是固件实际发出的时刻。**不是上位机收到的时刻** —— 这是
    Wi-Fi 连接下时序仍然可信的原因。
    """
    can_id: int = 0
    data: bytes = b""
    chn: int = Chn.CANFD
    ts_us: int = 0
    fd: bool = False
    brs: bool = False
    esi: bool = False
    tx: bool = False
    ide: bool = False
    rtr: bool = False
    err: bool = False

    @property
    def dlc(self) -> int:
        return len_to_dlc(len(self.data))

    @property
    def direction(self) -> str:
        return "Tx" if self.tx else "Rx"

    def id_text(self) -> str:
        return f"{self.can_id:08X}x" if self.ide else f"{self.can_id:03X}"

    def data_text(self) -> str:
        return " ".join(f"{b:02X}" for b in self.data)

    def encode(self) -> bytes:
        raw_id = (self.can_id & ID_MASK)
        if self.ide:
            raw_id |= ID_IDE
        if self.rtr:
            raw_id |= ID_RTR
        if self.err:
            raw_id |= ID_ERR
        flags = 0
        if self.fd:
            flags |= F_FD
        if self.brs:
            flags |= F_BRS
        if self.esi:
            flags |= F_ESI
        if self.tx:
            flags |= F_TX
        payload = bytes(self.data)
        head = struct.pack(FRAME_FMT, self.ts_us, raw_id, self.chn,
                           len(payload), flags, 0)
        return head + payload + b"\x00" * _pad4(len(payload))

    @property
    def wire_size(self) -> int:
        n = len(self.data)
        return FRAME_HDR_SIZE + n + _pad4(n)

    @classmethod
    def decode(cls, buf: memoryview, offset: int = 0):
        """从 buf[offset:] 解一条帧，返回 (Frame, 新 offset)。"""
        if len(buf) - offset < FRAME_HDR_SIZE:
            raise BstpError("frame record truncated")
        ts, raw_id, chn, length, flags, _ = struct.unpack_from(FRAME_FMT, buf, offset)
        offset += FRAME_HDR_SIZE
        if length > 64:
            raise BstpError(f"frame length {length} > 64")
        if len(buf) - offset < length:
            raise BstpError("frame payload truncated")
        data = bytes(buf[offset:offset + length])
        offset += length + _pad4(length)
        return cls(
            can_id=raw_id & ID_MASK, data=data, chn=chn, ts_us=ts,
            fd=bool(flags & F_FD), brs=bool(flags & F_BRS),
            esi=bool(flags & F_ESI), tx=bool(flags & F_TX),
            ide=bool(raw_id & ID_IDE), rtr=bool(raw_id & ID_RTR),
            err=bool(raw_id & ID_ERR),
        ), offset


@dataclass
class CycSlot:
    """周期发送槽。

    槽位语义是**增量更新**：改一条报文的 data 只发这一条，固件原地改槽、
    不重置 next_due_us，保证「改值不扰乱相位」。period_us = 0 表示删除该槽。
    """
    slot_id: int
    frame: Frame
    period_us: int = 0
    e2e_cfg_idx: int = 0xFFFF
    precise: bool = False

    def encode(self) -> bytes:
        return struct.pack(CYC_FMT, self.period_us, self.slot_id,
                           self.e2e_cfg_idx, 1 if self.precise else 0, 0, 0) \
            + self.frame.encode()


@dataclass
class Stat:
    """固件 1 Hz 上报的状态。cyc_miss 与 jitter_p99_us 是周期引擎的时序质量指标。"""
    uptime_us: int = 0
    rx_frames: int = 0
    tx_frames: int = 0
    rx_drop: int = 0
    tx_fail: int = 0
    cyc_slots_active: int = 0
    cyc_miss: int = 0
    jitter_p99_us: int = 0
    bus_load_permille: int = 0
    err_state: int = ErrState.ACTIVE
    tec: int = 0
    rec: int = 0
    link_up: bool = False
    wifi_up: bool = False

    @property
    def bus_load_percent(self) -> float:
        return self.bus_load_permille / 10.0

    @property
    def err_name(self) -> str:
        return ErrState.name(self.err_state)

    def encode(self) -> bytes:
        return struct.pack(
            STAT_FMT, self.uptime_us, self.rx_frames, self.tx_frames,
            self.rx_drop, self.tx_fail, self.cyc_slots_active, self.cyc_miss,
            self.jitter_p99_us, self.bus_load_permille, self.err_state,
            self.tec, self.rec, 1 if self.link_up else 0,
            1 if self.wifi_up else 0)

    @classmethod
    def decode(cls, buf) -> "Stat":
        size = struct.calcsize(STAT_FMT)
        if len(buf) < size:
            raise BstpError("STAT payload truncated")
        (uptime, rx, tx, drop, fail, slots, miss, jitter, load,
         err, tec, rec, link, wifi) = struct.unpack_from(STAT_FMT, buf, 0)
        return cls(uptime, rx, tx, drop, fail, slots, miss, jitter, load,
                   err, tec, rec, bool(link), bool(wifi))


@dataclass
class Packet:
    """一个 BSTP UDP 包。"""
    msg_type: int
    seq: int = 0
    flags: int = 0
    payload: bytes = b""

    def encode(self) -> bytes:
        return struct.pack(HDR_FMT, MAGIC, VERSION, self.msg_type, self.seq,
                           len(self.payload), self.flags, 0) + self.payload

    @classmethod
    def decode(cls, raw: bytes) -> "Packet":
        if len(raw) < HDR_SIZE:
            raise BstpError(f"packet too short: {len(raw)}")
        magic, ver, mtype, seq, plen, flags, _ = struct.unpack_from(HDR_FMT, raw, 0)
        if magic != MAGIC:
            raise BstpError(f"bad magic {magic:#010x}")
        if ver != VERSION:
            raise BstpError(f"unsupported BSTP version {ver}")
        if len(raw) - HDR_SIZE < plen:
            raise BstpError("payload truncated")
        return cls(mtype, seq, flags, raw[HDR_SIZE:HDR_SIZE + plen])

    def frames(self) -> List[Frame]:
        """把 TX_FRAME / RX_FRAME 的批量负载拆成帧列表。"""
        out: List[Frame] = []
        view = memoryview(self.payload)
        offset = 0
        while offset < len(view):
            frame, offset = Frame.decode(view, offset)
            out.append(frame)
        return out


def pack_frames(frames: List[Frame], msg_type: int = MsgType.TX_FRAME,
                seq: int = 0) -> List[Packet]:
    """把帧列表按 MTU 切成多个批量包。

    批量可显著降低高负载下的包率：8 字节帧 @500k 满载约 4000 帧/s，
    批量后约 67 pps。
    带宽只省 ~4.8 倍，但每个 UDP 包在 lwIP + W5500 SPI 上都有固定开销，
    包率才是真瓶颈。
    """
    packets: List[Packet] = []
    chunk: List[bytes] = []
    used = 0
    for frame in frames:
        blob = frame.encode()
        if chunk and used + len(blob) > MAX_BATCH_PAYLOAD:
            packets.append(Packet(msg_type, seq, payload=b"".join(chunk)))
            seq = (seq + 1) & 0xFFFF
            chunk, used = [], 0
        chunk.append(blob)
        used += len(blob)
    if chunk:
        packets.append(Packet(msg_type, seq, payload=b"".join(chunk)))
    return packets


def ctrl_packet(command: int, arg: int = 0, seq: int = 0) -> Packet:
    return Packet(MsgType.CTRL, seq, payload=struct.pack("<BBH", command, 0, arg))


def filter_packet(can_id: int, chn: int, action: int, seq: int = 0) -> Packet:
    """action: 0 删除指定 / 1 增加 / 2 清空全部。can_id = 0 表示整条总线。"""
    return Packet(MsgType.FILTER_SET, seq,
                  payload=struct.pack("<IBBBB", can_id, chn, action, 0, 0))
