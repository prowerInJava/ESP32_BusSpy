#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :stat_page.py
@Description  :统计页 —— 总线负载 / 错误状态 / 周期引擎时序质量

数据有两个来源，**刻意分开显示**：
  设备侧  固件 1 Hz 上报的 STAT（总线负载、TEC/REC、cyc_miss、抖动）
  上位机  本地收包计数

两边对不上本身就是有用的信号：设备说发了 10000 帧、上位机只收到 9000，
说明链路在丢包。所以不做成一个数字。

cyc_miss 与 jitter_p99 是周期引擎的时序质量指标 —— 设计方案里 P2 的
验收判据（10ms 周期连跑 1 小时，抖动 p99 < 500us、cyc_miss = 0）就看这两个。
"""
import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, LEFT, W, X

from BusSpyTool.core.bstp import ErrState, Stat


class StatPage(tb.Frame):
    DEVICE_FIELDS = (
        ("uptime", "运行时长"),
        ("bus_load", "总线负载"),
        ("err_state", "错误状态"),
        ("tec_rec", "TEC / REC"),
        ("rx_tx", "设备收 / 发"),
        ("drop_fail", "丢弃 / 发送失败"),
        ("cyc", "周期槽 / miss"),
        ("jitter", "周期抖动 p99"),
        ("link", "链路"),
    )
    HOST_FIELDS = (
        ("h_rx", "收到帧"),
        ("h_tx", "发出帧"),
        ("h_pkt", "收到包"),
        ("h_bad", "坏包"),
        ("h_gap", "序号断裂"),
        ("h_buf", "缓冲占用"),
    )

    def __init__(self, master, owner):
        super().__init__(master, padding=12)
        self.owner = owner
        self._device_values = {}
        self._host_values = {}
        self._build()

    def _build(self):
        columns = tb.Frame(self)
        columns.pack(fill=BOTH, expand=True)

        left = tb.Labelframe(columns, text="设备侧（固件 STAT，1 Hz）", padding=12)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 6))
        for key, title in self.DEVICE_FIELDS:
            self._device_values[key] = self._add_row(left, title)

        right = tb.Labelframe(columns, text="上位机侧（本地计数）", padding=12)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=(6, 0))
        for key, title in self.HOST_FIELDS:
            self._host_values[key] = self._add_row(right, title)

        hint = tb.Label(
            self, bootstyle="secondary", justify="left",
            text=("提示：设备侧与上位机侧的收帧数差值即链路丢包。\n"
                  "cyc_miss > 0 表示固件周期引擎错过了发送时刻，"
                  "jitter p99 是周期发送的实测抖动。"))
        hint.pack(fill=X, pady=(12, 0), anchor=W)

    @staticmethod
    def _add_row(parent, title):
        row = tb.Frame(parent)
        row.pack(fill=X, pady=3)
        tb.Label(row, text=title, width=18, anchor=W).pack(side=LEFT)
        value = tb.Label(row, text="-", anchor=W, bootstyle="inverse-light")
        value.pack(side=LEFT, fill=X, expand=True)
        return value

    def refresh(self):
        self._refresh_host()
        device = self.owner.device
        if device is None:
            for label in self._device_values.values():
                label.configure(text="-")
            return
        self._refresh_device(device.stat)

    def _refresh_device(self, stat: Stat):
        set_text = lambda key, text: self._device_values[key].configure(text=text)
        seconds = stat.uptime_us / 1e6
        set_text("uptime", f"{seconds:,.1f} s")
        set_text("bus_load", f"{stat.bus_load_percent:.1f} %")

        style = "success" if stat.err_state == ErrState.ACTIVE else "danger"
        self._device_values["err_state"].configure(
            text=stat.err_name, bootstyle=f"inverse-{style}")
        set_text("tec_rec", f"{stat.tec} / {stat.rec}")
        set_text("rx_tx", f"{stat.rx_frames:,} / {stat.tx_frames:,}")
        set_text("drop_fail", f"{stat.rx_drop:,} / {stat.tx_fail:,}")

        miss_style = "success" if stat.cyc_miss == 0 else "danger"
        self._device_values["cyc"].configure(
            text=f"{stat.cyc_slots_active} 槽 / miss {stat.cyc_miss}",
            bootstyle=f"inverse-{miss_style}")
        set_text("jitter", f"{stat.jitter_p99_us} us")
        set_text("link", ("以太网 " if stat.link_up else "") +
                 ("Wi-Fi" if stat.wifi_up else "") or "未连接")

    def _refresh_host(self):
        buffer = self.owner.buffer
        device = self.owner.device
        counters = device.counters if device else None
        set_text = lambda key, text: self._host_values[key].configure(text=text)
        set_text("h_rx", f"{counters.rx_frames:,}" if counters else "-")
        set_text("h_tx", f"{counters.tx_frames:,}" if counters else "-")
        set_text("h_pkt", f"{counters.rx_packets:,}" if counters else "-")
        set_text("h_bad", f"{counters.bad_packets:,}" if counters else "-")
        set_text("h_gap", f"{counters.seq_gaps:,}" if counters else "-")
        set_text("h_buf", f"{len(buffer):,} / {buffer.capacity:,}")
