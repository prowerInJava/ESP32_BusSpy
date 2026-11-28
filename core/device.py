#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :device.py
@Description  :ESP32-BusSpyTool 设备会话

职责：收发线程、周期槽管理、状态轮询、帧分发给订阅者。
物理链路由 core.transport 负责（USB CDC / UDP），本层不碰 socket 或串口。
不碰界面、不 import ui —— 无 X 的机器上也要能用。

通道模型（见 bstp.Chn）：
    0  CAN-FD 1       当前阶段通道（MCP2518FD）
    1  CAN 2.0B 1     预留，计划由 ESP32-S3 TWAI 实现
    2  ETH             以太网侧信号，经 W5500 与被测 ECU 直接收发
    3  CAN-FD 2       预留
    4  CAN 2.0B 2     预留
    5  CAN 2.0B 3     预留

时间戳一律用帧里的 ts_us（固件侧 MCP2518FD 硬件 TBC），**不用上位机收包时刻** ——
所以即使链路走 Wi-Fi 有抖动，时序判定依然可信。
"""
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from BusSpyTool.core import bstp
from BusSpyTool.core.bstp import Chn, Ctrl, Frame, MsgType, Packet, Stat
from BusSpyTool.core.transport import SerialTransport, Transport, UdpTransport
from BusSpyTool.utils.logger import logger


@dataclass
class Counters:
    """上位机侧统计。与固件 STAT 分开 —— 两边对不上本身就是有用的信号
    （说明链路丢包）。"""
    rx_frames: int = 0
    tx_frames: int = 0
    rx_packets: int = 0
    bad_packets: int = 0
    seq_gaps: int = 0


class Device:
    """一台 ESP32-BusSpyTool 的会话。

    线程模型：一个接收线程 + 一个状态轮询线程，都是 daemon。
    listener 在接收线程里被调用，**不要在 listener 里直接碰 Tk 控件** ——
    UI 侧应把帧丢进队列，由 after() 消费。
    """

    def __init__(self, transport: Transport):
        self.transport = transport
        self._rx_thread: Optional[threading.Thread] = None
        self._stat_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._last_rx_seq: Optional[int] = None

        self.connected = False
        self.counters = Counters()
        self.stat: Stat = Stat()
        self._listeners: List[Callable[[List[Frame]], None]] = []
        self._stat_listeners: List[Callable[[Stat], None]] = []
        self._cyc_slots: Dict[int, bstp.CycSlot] = {}
        self._next_slot = 0

    # ---------- 工厂 ----------

    @classmethod
    def over_usb(cls, port: str, baudrate: int = 921600) -> "Device":
        return cls(SerialTransport(port, baudrate))

    @classmethod
    def over_udp(cls, host: str, port: int = 8000) -> "Device":
        return cls(UdpTransport(host, port))

    @property
    def description(self) -> str:
        return self.transport.description

    # ---------- 生命周期 ----------

    def connect(self) -> bool:
        if self.connected:
            return True
        if not self.transport.open():
            return False

        self._stop.clear()
        self._last_rx_seq = None
        self.connected = True

        self._rx_thread = threading.Thread(target=self._rx_loop, name="bstp-rx", daemon=True)
        self._rx_thread.start()
        self._stat_thread = threading.Thread(target=self._stat_loop, name="bstp-stat", daemon=True)
        self._stat_thread.start()

        self._send(Packet(MsgType.HELLO, self._take_seq()))
        logger.info("已连接 %s", self.transport.description)
        return True

    def disconnect(self):
        if not self.connected:
            return
        self._stop.set()
        self.connected = False
        for thread in (self._rx_thread, self._stat_thread):
            if thread and thread.is_alive():
                thread.join(timeout=1.5)
        self.transport.close()
        logger.info("已断开 %s", self.transport.description)

    # ---------- 订阅 ----------

    def add_listener(self, callback: Callable[[List[Frame]], None]):
        self._listeners.append(callback)

    def add_stat_listener(self, callback: Callable[[Stat], None]):
        self._stat_listeners.append(callback)

    # ---------- 发送 ----------

    def _take_seq(self) -> int:
        with self._seq_lock:
            self._seq = (self._seq + 1) & 0xFFFF
            return self._seq

    def _send(self, packet: Packet) -> bool:
        return self.transport.send(packet)

    def send_frames(self, frames: List[Frame]) -> bool:
        """批量发帧。按 MTU 自动切包。"""
        if not frames:
            return True
        ok = True
        for packet in bstp.pack_frames(frames, MsgType.TX_FRAME, self._take_seq()):
            ok = self._send(packet) and ok
        if ok:
            self.counters.tx_frames += len(frames)
        return ok

    def send_frame(self, frame: Frame) -> bool:
        return self.send_frames([frame])

    # ---------- 周期发送 ----------

    def add_cyc(self, frame: Frame, period_us: int, precise: bool = False,
                e2e_cfg_idx: int = 0xFFFF) -> int:
        """新增周期槽，返回 slot_id。周期调度在固件本地，不受链路抖动影响。"""
        slot_id = self._next_slot
        self._next_slot += 1
        slot = bstp.CycSlot(slot_id, frame, period_us, e2e_cfg_idx, precise)
        self._cyc_slots[slot_id] = slot
        self._push_cyc([slot])
        return slot_id

    def update_cyc(self, slot_id: int, frame: Optional[Frame] = None,
                   period_us: Optional[int] = None) -> bool:
        """改槽。固件原地改、不重置 next_due_us —— 改值不扰乱相位。"""
        slot = self._cyc_slots.get(slot_id)
        if slot is None:
            return False
        if frame is not None:
            slot.frame = frame
        if period_us is not None:
            slot.period_us = period_us
        return self._push_cyc([slot])

    def remove_cyc(self, slot_id: int) -> bool:
        slot = self._cyc_slots.pop(slot_id, None)
        if slot is None:
            return False
        slot.period_us = 0          # 0 = 删除该槽
        return self._push_cyc([slot])

    def clear_cyc(self):
        slots = list(self._cyc_slots.values())
        self._cyc_slots.clear()
        for slot in slots:
            slot.period_us = 0
        if slots:
            self._push_cyc(slots)

    @property
    def cyc_slots(self) -> List[bstp.CycSlot]:
        return list(self._cyc_slots.values())

    def _push_cyc(self, slots: List[bstp.CycSlot]) -> bool:
        payload = b"".join(s.encode() for s in slots)
        return self._send(Packet(MsgType.CYC_SET, self._take_seq(), payload=payload))

    # ---------- 过滤 / 控制 ----------

    def set_filter(self, can_id: int, chn: int, action: int) -> bool:
        return self._send(bstp.filter_packet(can_id, chn, action, self._take_seq()))

    def clear_filters(self, chn: int = Chn.CANFD) -> bool:
        return self.set_filter(0, chn, 2)

    def control(self, command: int, arg: int = 0) -> bool:
        return self._send(bstp.ctrl_packet(command, arg, self._take_seq()))

    def bus_on(self):
        return self.control(Ctrl.BUS_ON)

    def bus_off(self):
        return self.control(Ctrl.BUS_OFF)

    def reset(self):
        return self.control(Ctrl.RESET)

    # ---------- 接收 ----------

    def _rx_loop(self):
        while not self._stop.is_set():
            try:
                packets = self.transport.recv(timeout=0.2)
            except Exception as error:
                logger.warning("接收异常: %s", error)
                break
            for packet in packets:
                self.counters.rx_packets += 1
                self._dispatch(packet)
        # 把链路层统计并进来，UI 只看一处
        self.counters.bad_packets = getattr(self.transport, "bad_packets", 0)

    def _dispatch(self, packet: Packet):
        if packet.msg_type == MsgType.RX_FRAME:
            self._track_seq(packet.seq)
            try:
                frames = packet.frames()
            except bstp.BstpError:
                self.counters.bad_packets += 1
                return
            self.counters.rx_frames += len(frames)
            for callback in self._listeners:
                try:
                    callback(frames)
                except Exception as error:
                    logger.debug("帧监听回调异常: %s", error)
        elif packet.msg_type == MsgType.STAT:
            try:
                self.stat = Stat.decode(packet.payload)
            except bstp.BstpError:
                self.counters.bad_packets += 1
                return
            for callback in self._stat_listeners:
                try:
                    callback(self.stat)
                except Exception as error:
                    logger.debug("状态监听回调异常: %s", error)
        elif packet.msg_type == MsgType.ERROR:
            logger.warning("设备报错: %s", packet.payload[:120])

    def _track_seq(self, seq: int):
        if self._last_rx_seq is not None:
            expected = (self._last_rx_seq + 1) & 0xFFFF
            if seq != expected:
                self.counters.seq_gaps += 1
        self._last_rx_seq = seq

    def _stat_loop(self):
        while not self._stop.is_set():
            self._send(Packet(MsgType.STAT, self._take_seq()))
            self._stop.wait(1.0)
