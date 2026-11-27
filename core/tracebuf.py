#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :tracebuf.py
@Description  :Trace 缓冲 —— 环形存储 + 按 ID 聚合

这个模块是整个上位机的性能关键。CANoe 类工具卡顿的根因几乎都不是
语言，而是「每来一帧就往列表控件里插一行」。本实现按两条原则做：

  1. **固定模式（聚合）是默认**。按 (通道, ID, 扩展位) 聚合，行数等于
     总线上的唯一报文数（几十到几百），**不随时间增长**。CANoe 的 Trace
     默认就是这个模式。滚动模式只保留最近 N 行。
  2. **惰性解码**。缓冲里只存原始帧，信号解码由 UI 对**可见行**按需做。
     全量解码 4000 帧/s 会吃掉 30% CPU，而用户一次最多看见几十行。

线程安全：extend() 在接收线程调用，其余在 UI 线程调用，用一把锁。
"""
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from BusSpyTool.core.bstp import Frame

# 滚动模式保留的帧数。10 万帧约 20 MB，够看很久又不至于吃光内存。
DEFAULT_CAPACITY = 100_000

Key = Tuple[int, int, bool]       # (chn, can_id, is_extended)


@dataclass
class Aggregate:
    """一个报文 ID 的聚合统计，对应 CANoe Trace 固定模式的一行。"""
    chn: int
    can_id: int
    ide: bool
    count: int = 0
    tx_count: int = 0
    last: Optional[Frame] = None
    first_ts_us: int = 0
    last_ts_us: int = 0
    period_us: float = 0.0        # 实测周期（指数滑动平均）
    min_period_us: Optional[int] = None
    max_period_us: Optional[int] = None

    def update(self, frame: Frame):
        if self.count == 0:
            self.first_ts_us = frame.ts_us
        elif frame.ts_us > self.last_ts_us:
            delta = frame.ts_us - self.last_ts_us
            # EMA 平滑：单次抖动不该让显示的周期跳来跳去，
            # 但真实的周期变化要在一秒内跟上
            self.period_us = delta if self.period_us == 0 else \
                self.period_us * 0.8 + delta * 0.2
            if self.min_period_us is None or delta < self.min_period_us:
                self.min_period_us = delta
            if self.max_period_us is None or delta > self.max_period_us:
                self.max_period_us = delta
        self.count += 1
        if frame.tx:
            self.tx_count += 1
        self.last = frame
        self.last_ts_us = frame.ts_us

    @property
    def period_ms(self) -> float:
        return self.period_us / 1000.0

    @property
    def jitter_us(self) -> Optional[int]:
        """实测周期抖动区间。用来肉眼发现时序异常。"""
        if self.min_period_us is None or self.max_period_us is None:
            return None
        return self.max_period_us - self.min_period_us


class TraceBuffer:
    """帧缓冲。同时维护滚动窗口与聚合表，两种 Trace 模式共用一份数据。"""

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self.capacity = capacity
        self._lock = threading.Lock()
        self._frames: deque = deque(maxlen=capacity)
        self._aggregates: "OrderedDict[Key, Aggregate]" = OrderedDict()
        self._pending: List[Frame] = []
        self.total_received = 0
        self.dropped = 0
        self.paused = False

    # ---------- 写入（接收线程） ----------

    def extend(self, frames: List[Frame]):
        """批量加入。接收线程调用，必须快 —— 这里只做记账，不做解码。"""
        if not frames:
            return
        with self._lock:
            if self.paused:
                # 暂停时仍更新计数，让用户看到「暂停期间漏了多少」
                self.dropped += len(frames)
                self.total_received += len(frames)
                return
            before = len(self._frames)
            self._frames.extend(frames)
            overflow = before + len(frames) - self.capacity
            if overflow > 0:
                self.dropped += overflow
            self._pending.extend(frames)
            self.total_received += len(frames)
            for frame in frames:
                key = (frame.chn, frame.can_id, frame.ide)
                agg = self._aggregates.get(key)
                if agg is None:
                    agg = Aggregate(frame.chn, frame.can_id, frame.ide)
                    self._aggregates[key] = agg
                agg.update(frame)

    # ---------- 读取（UI 线程） ----------

    def drain_pending(self, limit: int = 2000) -> List[Frame]:
        """取走自上次以来的新帧，供滚动模式增量渲染。

        limit 是刹车：高负载下一次刷新最多渲染这么多行，剩下的下一轮再来。
        没有它的话一次 UI 回调可能要插几万行，界面会假死。
        """
        with self._lock:
            if not self._pending:
                return []
            if len(self._pending) <= limit:
                out = self._pending
                self._pending = []
                return out
            out = self._pending[:limit]
            del self._pending[:limit]
            return out

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def aggregates(self) -> List[Aggregate]:
        with self._lock:
            return list(self._aggregates.values())

    def recent(self, count: int) -> List[Frame]:
        with self._lock:
            if count >= len(self._frames):
                return list(self._frames)
            return list(self._frames)[-count:]

    def all_frames(self) -> List[Frame]:
        with self._lock:
            return list(self._frames)

    def __len__(self):
        with self._lock:
            return len(self._frames)

    # ---------- 控制 ----------

    def set_paused(self, paused: bool):
        with self._lock:
            self.paused = paused

    def clear(self):
        with self._lock:
            self._frames.clear()
            self._aggregates.clear()
            self._pending.clear()
            self.total_received = 0
            self.dropped = 0
