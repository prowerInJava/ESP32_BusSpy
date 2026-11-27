#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :graph_page.py
@Description  :信号波形图 —— 仿 CANoe 的 Graphics 窗口

用 tkinter Canvas 自绘，不用 matplotlib：后者 PyInstaller 打包要多 40 MB，
实时重绘还更慢，而我们要的就是折线 + 网格 + 游标。

采样策略（性能关键）：
  在接收线程里对帧做**快速 ID 筛选**，只有被监视的报文才解码。
  被监视的通常就几条，解码量与总线帧率无关 —— 这样 10ms 周期的信号
  能按真实周期采样，而不是被 UI 的 10Hz 刷新率抹平。

绘制时按画布像素宽度降采样：60 秒窗口 × 10ms 周期 = 6000 点，
画布只有 ~900 像素，每像素取一个点即可，画 6000 条线段纯属浪费。
"""
import threading
import tkinter as tk
from collections import deque
from typing import Dict, List, Optional, Tuple

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, W, X, Y

# 区分度高的配色，依次分配给各条曲线
PALETTE = ("#2e86de", "#ee5253", "#10ac84", "#f368e0", "#ff9f43",
           "#54a0ff", "#01a3a4", "#c8d6e5", "#5f27cd", "#feca57")

WINDOWS = (("1 秒", 1), ("5 秒", 5), ("10 秒", 10),
           ("30 秒", 30), ("60 秒", 60), ("5 分钟", 300))

MAX_POINTS = 60_000          # 每条曲线最多留这么多采样点


class Series:
    """一条曲线。points 在接收线程里 append，UI 线程只读 —— deque 的
    append/popleft 是原子的，这个用法不需要额外加锁。"""

    def __init__(self, message, signal, color: str):
        self.message = message
        self.signal = signal
        self.color = color
        self.visible = True
        self.points: deque = deque(maxlen=MAX_POINTS)
        self.last_value = None

    @property
    def label(self) -> str:
        # 图例列窄，显示信号名即可；报文名在「信号」页能看到完整对应关系
        return self.signal.name

    @property
    def key(self) -> Tuple[int, bool, str]:
        return (self.message.frame_id, self.message.is_extended, self.signal.name)


class GraphPage(tb.Frame):
    def __init__(self, master, owner):
        super().__init__(master, padding=6)
        self.owner = owner
        self.series: Dict[str, Series] = {}
        self._watched: Dict[Tuple[int, bool], List[Series]] = {}
        self._lock = threading.Lock()
        self._t0_us: Optional[int] = None
        self._latest_us = 0
        self.window_s = tk.IntVar(value=10)
        self.paused = tk.BooleanVar(value=False)
        self._cursor_x: Optional[int] = None
        self._build()
        owner.register_frame_listener(self._on_frames)

    # ---------- 布局 ----------

    def _build(self):
        bar = tb.Frame(self)
        bar.pack(fill=X, pady=(0, 6))
        tb.Button(bar, text="添加信号…", bootstyle="primary",
                  command=self._add_dialog).pack(side=LEFT, padx=2)
        tb.Button(bar, text="删除选中", bootstyle="danger-outline",
                  command=self._remove_selected).pack(side=LEFT, padx=2)
        tb.Button(bar, text="清空数据", bootstyle="warning-outline",
                  command=self.clear_data).pack(side=LEFT, padx=2)

        tb.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=10)
        tb.Label(bar, text="时间窗口").pack(side=LEFT, padx=(0, 4))
        self.window_combo = tb.Combobox(
            bar, width=8, state="readonly",
            values=[text for text, _ in WINDOWS])
        self.window_combo.set("10 秒")
        self.window_combo.pack(side=LEFT)
        self.window_combo.bind("<<ComboboxSelected>>", self._on_window)

        tb.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=10)
        tb.Checkbutton(bar, text="暂停", variable=self.paused,
                       bootstyle="round-toggle").pack(side=LEFT, padx=4)
        tb.Label(bar, text="Y轴").pack(side=LEFT, padx=(10, 3))
        self.scale_mode = tk.StringVar(value="each")
        tb.Radiobutton(bar, text="各自缩放", value="each",
                       variable=self.scale_mode,
                       bootstyle="toolbutton").pack(side=LEFT, padx=2)
        tb.Radiobutton(bar, text="共用", value="shared",
                       variable=self.scale_mode,
                       bootstyle="toolbutton").pack(side=LEFT, padx=2)

        self.readout = tb.Label(bar, text="", bootstyle="secondary")
        self.readout.pack(side=RIGHT)

        body = tb.Frame(self)
        body.pack(fill=BOTH, expand=True)

        legend = tb.Labelframe(body, text="曲线", padding=4, width=320)
        legend.pack(side=LEFT, fill=Y, padx=(0, 6))
        legend.pack_propagate(False)
        self.legend = tb.Treeview(legend, columns=("value",), show="tree headings",
                                  bootstyle="info", height=12)
        self.legend.heading("#0", text="信号")
        self.legend.heading("value", text="当前值")
        self.legend.column("#0", width=190)
        self.legend.column("value", width=108, anchor="e")
        self.legend.pack(fill=BOTH, expand=True)

        self.canvas = tk.Canvas(body, bg="#11161c", highlightthickness=0)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)

    # ---------- 数据采集（接收线程） ----------

    def _on_frames(self, frames):
        """在接收线程里跑。只做 ID 快速筛选 + 被监视报文的解码。"""
        if self.paused.get() or not self._watched:
            return
        for frame in frames:
            key = (frame.can_id, frame.ide)
            series_list = self._watched.get(key)
            if not series_list:
                continue
            _info, decoded = self.owner.decode_frame(frame)
            if not decoded:
                continue
            if self._t0_us is None:
                self._t0_us = frame.ts_us
            elapsed = (frame.ts_us - self._t0_us) / 1e6
            self._latest_us = frame.ts_us
            for series in series_list:
                value = decoded.get(series.signal.name)
                if value is None:
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                series.points.append((elapsed, numeric))
                series.last_value = numeric

    def _rebuild_watch(self):
        watched: Dict[Tuple[int, bool], List[Series]] = {}
        for series in self.series.values():
            key = (series.message.frame_id, series.message.is_extended)
            watched.setdefault(key, []).append(series)
        self._watched = watched

    # ---------- 列表 ----------

    def _add_dialog(self):
        messages = self.owner.databases.all_messages()
        if not messages:
            tk.messagebox.showinfo(
                "没有数据库", "请先通过「数据库 -> 加载 DBC/ARXML」载入数据库")
            return
        from BusSpyTool.ui.signal_page import SignalPickDialog
        SignalPickDialog(self, messages, self._add_series)

    def _add_series(self, picks):
        for message, signal in picks:
            color = PALETTE[len(self.series) % len(PALETTE)]
            series = Series(message, signal, color)
            if any(existing.key == series.key for existing in self.series.values()):
                continue
            iid = self.legend.insert("", END, text=series.label, values=("-",),
                                     tags=(series.color,))
            self.legend.tag_configure(series.color, foreground=series.color)
            self.series[iid] = series
        self._rebuild_watch()

    def _remove_selected(self):
        for iid in self.legend.selection():
            self.legend.delete(iid)
            self.series.pop(iid, None)
        self._rebuild_watch()

    def clear_data(self):
        for series in self.series.values():
            series.points.clear()
            series.last_value = None
        self._t0_us = None
        self.canvas.delete("all")

    # ---------- 工程序列化 ----------

    def to_config(self) -> list:
        return [{"message": s.message.name, "signal": s.signal.name,
                 "color": s.color}
                for s in self.series.values()]

    def from_config(self, items) -> None:
        self.legend.delete(*self.legend.get_children())
        self.series.clear()
        self._rebuild_watch()
        by_name = {m.name: m for m in self.owner.databases.all_messages()}
        picks = []
        for entry in items or []:
            message = by_name.get(entry.get("message"))
            if message is None:
                continue
            signal = next((s for s in message.signals
                           if s.name == entry.get("signal")), None)
            if signal is not None:
                picks.append((message, signal))
        if picks:
            self._add_series(picks)
        # 恢复用户调过的颜色
        for iid, entry in zip(self.legend.get_children(), items or []):
            series = self.series.get(iid)
            if series and entry.get("color"):
                series.color = entry["color"]
                self.legend.tag_configure(series.color, foreground=series.color)
                self.legend.item(iid, tags=(series.color,))

    def _on_window(self, _event=None):
        text = self.window_combo.get()
        for label, seconds in WINDOWS:
            if label == text:
                self.window_s.set(seconds)
                break

    # ---------- 绘制 ----------

    def refresh(self):
        self._draw()
        for iid, series in self.series.items():
            if not self.legend.exists(iid):
                continue
            value = series.last_value
            unit = series.signal.unit
            text = "-" if value is None else f"{value:g} {unit}".strip()
            self.legend.set(iid, "value", text)

    def _draw(self):
        canvas = self.canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 50 or height < 50:
            return

        pad_l, pad_r, pad_t, pad_b = 78, 14, 12, 26
        plot_w = width - pad_l - pad_r
        plot_h = height - pad_t - pad_b
        if plot_w <= 0 or plot_h <= 0:
            return

        visible = [s for s in self.series.values() if s.visible and s.points]
        window = self.window_s.get()
        per_series = self.scale_mode.get() == "each"

        # X 轴范围：跟随最新采样点
        t_end = max((s.points[-1][0] for s in visible), default=0.0)
        t_start = max(0.0, t_end - window)

        # 每条曲线在窗口内的值域
        ranges = {}
        for series in visible:
            values = [v for t, v in series.points if t >= t_start]
            if values:
                low, high = min(values), max(values)
            else:
                low, high = 0.0, 1.0
            if high - low < 1e-9:
                low, high = low - 1.0, high + 1.0
            margin = (high - low) * 0.08
            ranges[id(series)] = (low - margin, high + margin)

        if per_series:
            # 各自缩放：Y 轴画百分比。混合量纲时唯一能同屏看的方式
            axis_min, axis_max, axis_pct = 0.0, 1.0, True
        else:
            lows = [r[0] for r in ranges.values()] or [0.0]
            highs = [r[1] for r in ranges.values()] or [1.0]
            axis_min, axis_max, axis_pct = min(lows), max(highs), False

        self._draw_grid(canvas, pad_l, pad_t, plot_w, plot_h,
                        t_start, t_end, axis_min, axis_max, axis_pct)

        for series in visible:
            low, high = ranges[id(series)] if per_series else (axis_min, axis_max)
            self._draw_series(canvas, series, pad_l, pad_t, plot_w, plot_h,
                              t_start, t_end, low, high)

        if self._cursor_x is not None and pad_l <= self._cursor_x <= pad_l + plot_w:
            canvas.create_line(self._cursor_x, pad_t, self._cursor_x,
                               pad_t + plot_h, fill="#5a6676", dash=(2, 2))
            ratio = (self._cursor_x - pad_l) / plot_w
            stamp = t_start + ratio * max(1e-9, t_end - t_start)
            self.readout.configure(text=f"游标 t = {stamp:.3f} s")

    @staticmethod
    def _draw_grid(canvas, pad_l, pad_t, plot_w, plot_h,
                   t_start, t_end, y_min, y_max, as_percent=False):
        canvas.create_rectangle(pad_l, pad_t, pad_l + plot_w, pad_t + plot_h,
                                outline="#2b3440", fill="#161c24")
        rows = 5
        for index in range(rows + 1):
            y = pad_t + plot_h * index / rows
            canvas.create_line(pad_l, y, pad_l + plot_w, y, fill="#232c38")
            if as_percent:
                text = f"{100 - 100 * index / rows:.0f}%"
            else:
                value = y_max - (y_max - y_min) * index / rows
                text = f"{value:.4g}"
            canvas.create_text(pad_l - 6, y, anchor="e", fill="#8b97a6",
                               font=("Consolas", 8), text=text)
        cols = 6
        for index in range(cols + 1):
            x = pad_l + plot_w * index / cols
            canvas.create_line(x, pad_t, x, pad_t + plot_h, fill="#232c38")
            stamp = t_start + (t_end - t_start) * index / cols
            canvas.create_text(x, pad_t + plot_h + 12, anchor="n",
                               fill="#8b97a6", font=("Consolas", 8),
                               text=f"{stamp:.2f}")

    @staticmethod
    def _draw_series(canvas, series, pad_l, pad_t, plot_w, plot_h,
                     t_start, t_end, y_min, y_max):
        span_t = max(1e-9, t_end - t_start)
        span_y = max(1e-9, y_max - y_min)

        # 按像素降采样：每个 x 像素只保留一个点，60 秒 10ms 周期有 6000 点，
        # 画布才 ~900 像素，全画是浪费
        buckets: Dict[int, Tuple[float, float]] = {}
        for stamp, value in series.points:
            if stamp < t_start:
                continue
            x = int(pad_l + (stamp - t_start) / span_t * plot_w)
            buckets[x] = (stamp, value)
        if len(buckets) < 2:
            return

        coords = []
        previous = None
        for x in sorted(buckets):
            _stamp, value = buckets[x]
            y = pad_t + plot_h - (value - y_min) / span_y * plot_h
            if previous is not None:
                # 阶梯线：CAN 信号是离散采样，两点之间应保持上一个值，
                # 直接连斜线会让人误以为信号是连续变化的
                coords.extend([x, previous])
            coords.extend([x, y])
            previous = y
        canvas.create_line(*coords, fill=series.color, width=1.6, smooth=False)

    # ---------- 游标 ----------

    def _on_motion(self, event):
        self._cursor_x = event.x

    def _on_leave(self, _event):
        self._cursor_x = None
        self.readout.configure(text="")
