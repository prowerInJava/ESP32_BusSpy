#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :mock.py
@Description  :模拟设备 —— 没有 ESP32 硬件时让界面完整跑起来

用途有三个，都不是玩具：
  1. W5500 到货前、固件写好前就能把 UI 调完
  2. 演示与截图
  3. 回归测试 UI 的热路径（高帧率下 Trace 不卡、不漏）

对外接口与 core.device.Device 完全一致（鸭子类型），UI 不需要知道
自己连的是真设备还是模拟器。
"""
import math
import random
import threading
import time
from typing import Callable, Dict, List, Optional

from BusSpyTool.core import bstp
from BusSpyTool.core.bstp import Chn, Frame, Stat
from BusSpyTool.core.device import Counters
from BusSpyTool.utils.logger import logger

# (can_id, 字节数, 周期 ms, 是否 FD)
_DEFAULT_TRAFFIC = (
    (0x123, 8, 10, False),
    (0x1A0, 8, 20, False),
    (0x245, 64, 10, True),
    (0x2B1, 32, 50, True),
    (0x300, 8, 100, False),
    (0x18FEF100, 8, 1000, False),
)


class MockDevice:
    """假装是一台 ESP32-BusSpyTool。

    时间戳用自己的单调时钟模拟固件侧硬件 TBC，所以 Trace 上的时序
    看起来与真设备一致（真设备的 ts_us 来自 MCP2518FD 的 TBC）。
    """

    def __init__(self, host: str = "mock", port: int = 0, frame_rate: int = 400):
        self.host = host
        self.port = port
        self.frame_rate = frame_rate
        self.connected = False
        self.counters = Counters()
        self.stat = Stat(link_up=False, wifi_up=True)

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listeners: List[Callable[[List[Frame]], None]] = []
        self._stat_listeners: List[Callable[[Stat], None]] = []
        self._cyc_slots: Dict[int, bstp.CycSlot] = {}
        self._next_slot = 0
        self._t0 = time.monotonic()
        self._extra: List[Frame] = []
        self._extra_lock = threading.Lock()
        # (can_id, 字节数, 是否FD, 是否扩展帧)
        self._traffic = [(i, n, fd, i > 0x7FF)
                         for i, n, _c, fd in _DEFAULT_TRAFFIC]

    def load_traffic(self, messages, limit: int = 40):
        """按真实数据库的报文定义产流量。

        不这么做的话 mock 的 ID 匹配不上任何数据库，Trace 的报文名、
        信号解码、波形图全都验证不到 —— 只能看到一堆 hex。
        """
        traffic = []
        for info in messages[:limit]:
            size = max(1, min(64, info.length))
            traffic.append((info.frame_id, size,
                            bool(info.is_fd or size > 8),
                            bool(info.is_extended)))
        if traffic:
            self._traffic = traffic
            logger.info("模拟流量已按数据库重建：%d 条报文", len(traffic))

    # ---------- 生命周期 ----------

    def connect(self) -> bool:
        if self.connected:
            return True
        self._stop.clear()
        self._t0 = time.monotonic()
        self.connected = True
        self.stat = Stat(link_up=True, wifi_up=True)
        self._thread = threading.Thread(target=self._loop, name="mock-dev", daemon=True)
        self._thread.start()
        logger.info("模拟设备已启动（%d 帧/秒）", self.frame_rate)
        return True

    def disconnect(self):
        if not self.connected:
            return
        self._stop.set()
        self.connected = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("模拟设备已停止")

    # ---------- 订阅 ----------

    def add_listener(self, callback):
        self._listeners.append(callback)

    def add_stat_listener(self, callback):
        self._stat_listeners.append(callback)

    # ---------- 发送 ----------

    def send_frames(self, frames: List[Frame]) -> bool:
        """模拟发送：回显为 Tx 方向的帧，这样 Trace 里能看到自己发的东西。"""
        now = self._now_us()
        with self._extra_lock:
            for frame in frames:
                echo = Frame(
                    can_id=frame.can_id, data=frame.data, chn=frame.chn,
                    ts_us=now, fd=frame.fd, brs=frame.brs, tx=True,
                    ide=frame.ide, rtr=frame.rtr)
                self._extra.append(echo)
        self.counters.tx_frames += len(frames)
        return True

    def send_frame(self, frame: Frame) -> bool:
        return self.send_frames([frame])

    # ---------- 周期发送 ----------

    def add_cyc(self, frame: Frame, period_us: int, precise: bool = False,
                e2e_cfg_idx: int = 0xFFFF) -> int:
        slot_id = self._next_slot
        self._next_slot += 1
        self._cyc_slots[slot_id] = bstp.CycSlot(slot_id, frame, period_us,
                                                e2e_cfg_idx, precise)
        return slot_id

    def update_cyc(self, slot_id: int, frame: Optional[Frame] = None,
                   period_us: Optional[int] = None) -> bool:
        slot = self._cyc_slots.get(slot_id)
        if slot is None:
            return False
        if frame is not None:
            slot.frame = frame
        if period_us is not None:
            slot.period_us = period_us
        return True

    def remove_cyc(self, slot_id: int) -> bool:
        return self._cyc_slots.pop(slot_id, None) is not None

    def clear_cyc(self):
        self._cyc_slots.clear()

    @property
    def cyc_slots(self) -> List[bstp.CycSlot]:
        return list(self._cyc_slots.values())

    # ---------- 过滤 / 控制 ----------

    def set_filter(self, can_id: int, chn: int, action: int) -> bool:
        return True

    def clear_filters(self, chn: int = Chn.CANFD) -> bool:
        return True

    def control(self, command: int, arg: int = 0) -> bool:
        return True

    def bus_on(self):
        return True

    def bus_off(self):
        return True

    def reset(self):
        self.counters = Counters()
        return True

    # ---------- 内部 ----------

    def _now_us(self) -> int:
        return int((time.monotonic() - self._t0) * 1_000_000)

    def _loop(self):
        """按 frame_rate 产出批量帧，并 1 Hz 推状态。

        刻意做成**批量**投递（与真设备的 BSTP 批量包一致），这样 UI 的
        热路径就是按批处理的，不会在真设备上才发现逐帧刷新卡顿。
        """
        tick = 0.05                       # 50ms 一批，20 批/秒
        per_batch = max(1, int(self.frame_rate * tick))
        phase: Dict[int, float] = {}
        next_stat = time.monotonic() + 1.0

        while not self._stop.is_set():
            batch: List[Frame] = []
            now_us = self._now_us()
            elapsed_s = now_us / 1e6

            for index in range(per_batch):
                can_id, size, is_fd, is_ext = self._traffic[index % len(self._traffic)]
                # 让信号值随时间平滑变化，波形图上才看得出曲线而不是噪声
                wave = int((math.sin(elapsed_s * 0.8 + can_id * 0.01) * 0.5 + 0.5) * 255)
                data = bytearray(random.getrandbits(8) for _ in range(size))
                data[0] = wave
                if size > 1:
                    data[1] = (wave * 2) % 256
                batch.append(Frame(
                    can_id=can_id, data=bytes(data),
                    chn=Chn.CANFD if is_fd else Chn.TWAI,
                    ts_us=now_us + index * 120,
                    fd=is_fd, brs=is_fd,
                    ide=is_ext,
                ))

            # 周期槽也产帧，让 Trace 上能看到周期报文
            for slot in list(self._cyc_slots.values()):
                if not slot.period_us:
                    continue
                period_s = slot.period_us / 1e6
                last = phase.get(slot.slot_id, 0.0)
                elapsed = (time.monotonic() - self._t0)
                if elapsed - last >= period_s:
                    phase[slot.slot_id] = elapsed
                    frame = slot.frame
                    batch.append(Frame(
                        can_id=frame.can_id, data=frame.data, chn=frame.chn,
                        ts_us=now_us, fd=frame.fd, brs=frame.brs, tx=True,
                        ide=frame.ide))

            with self._extra_lock:
                if self._extra:
                    batch.extend(self._extra)
                    self._extra.clear()

            if batch:
                self.counters.rx_frames += sum(1 for f in batch if not f.tx)
                self.counters.rx_packets += 1
                for callback in self._listeners:
                    try:
                        callback(batch)
                    except Exception as error:
                        logger.debug("模拟帧回调异常: %s", error)

            if time.monotonic() >= next_stat:
                next_stat += 1.0
                self._emit_stat()

            self._stop.wait(tick)

    def _emit_stat(self):
        self.stat = Stat(
            uptime_us=self._now_us(),
            rx_frames=self.counters.rx_frames,
            tx_frames=self.counters.tx_frames,
            rx_drop=0, tx_fail=0,
            cyc_slots_active=sum(1 for s in self._cyc_slots.values() if s.period_us),
            cyc_miss=0,
            jitter_p99_us=random.randint(20, 80),
            bus_load_permille=random.randint(250, 480),
            err_state=bstp.ErrState.ACTIVE,
            tec=0, rec=0, link_up=True, wifi_up=True,
        )
        for callback in self._stat_listeners:
            try:
                callback(self.stat)
            except Exception as error:
                logger.debug("模拟状态回调异常: %s", error)
