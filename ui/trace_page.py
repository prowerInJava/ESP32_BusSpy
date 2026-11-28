#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :trace_page.py
@Description  :Trace 页 —— 仿 CANoe 的核心窗口

两种模式（与 CANoe 一致）：
  固定模式  按 (通道, ID) 聚合，一个报文一行，显示实测周期与计数。
            行数不随时间增长，**高负载下不卡**，是默认模式。
  滚动模式  新帧追加到底部，限制最大行数。看时序细节时用。

信号解码是**惰性**的：只解码当前展开的那些行。全量解码 4000 帧/s 会吃掉
30% CPU，而用户一次最多看见几十行 —— CANoe 自己也是这么做的。
"""
import tkinter as tk
from typing import Dict, Optional, Tuple

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y

from BusSpyTool.core.bstp import CHANNEL_NAMES, Chn
from BusSpyTool.core.tracebuf import Aggregate, TraceBuffer

CHN_NAMES = CHANNEL_NAMES

MODE_FIXED = "fixed"
MODE_SCROLL = "scroll"

# 滚动模式最多保留的行数。Treeview 超过一两万行就明显迟钝，
# 这是控件的限制，不是 Python 的。
MAX_SCROLL_ROWS = 5000


class TracePage(tb.Frame):
    """Trace 页。owner 需提供 .buffer / .databases / .decode_frame。"""

    COLUMNS = (
        ("time", "时间", 100),
        ("chn", "通道", 150),
        ("dir", "方向", 60),
        ("id", "ID", 86),
        ("name", "报文名", 180),
        ("dlc", "长度", 60),
        ("period", "周期ms", 74),
        ("count", "计数", 70),
        ("data", "数据", 440),
    )

    def __init__(self, master, owner):
        super().__init__(master, padding=6)
        self.owner = owner
        self.buffer: TraceBuffer = owner.buffer
        self.mode = tk.StringVar(value=MODE_FIXED)
        self.autoscroll = tk.BooleanVar(value=True)
        self._rows: Dict[Tuple[int, int, bool], str] = {}
        self._scroll_rows = 0
        self._expanded: set = set()
        self._build()

    # ---------- 布局 ----------

    def _build(self):
        bar = tb.Frame(self)
        bar.pack(fill=X, pady=(0, 6))

        tb.Label(bar, text="模式").pack(side=LEFT, padx=(0, 4))
        tb.Radiobutton(bar, text="固定(聚合)", value=MODE_FIXED,
                       variable=self.mode, command=self._on_mode_change,
                       bootstyle="toolbutton").pack(side=LEFT, padx=2)
        tb.Radiobutton(bar, text="滚动", value=MODE_SCROLL,
                       variable=self.mode, command=self._on_mode_change,
                       bootstyle="toolbutton").pack(side=LEFT, padx=2)

        tb.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=6)
        tb.Checkbutton(bar, text="自动滚动", variable=self.autoscroll,
                       bootstyle="round-toggle").pack(side=LEFT, padx=4)

        tb.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=6)
        tb.Label(bar, text="过滤ID").pack(side=LEFT, padx=(0, 3))
        self.filter_var = tk.StringVar()
        entry = tb.Entry(bar, textvariable=self.filter_var, width=9)
        entry.pack(side=LEFT)
        entry.bind("<Return>", lambda _e: self.rebuild())
        tb.Button(bar, text="应用", bootstyle="secondary-outline", width=4,
                  command=self.rebuild).pack(side=LEFT, padx=3)
        tb.Button(bar, text="清空", bootstyle="warning-outline", width=4,
                  command=self.clear).pack(side=LEFT, padx=2)

        self.info = tb.Label(bar, text="", bootstyle="secondary")
        self.info.pack(side=RIGHT)

        holder = tb.Frame(self)
        holder.pack(fill=BOTH, expand=True)

        self.tree = tb.Treeview(
            holder, columns=[c[0] for c in self.COLUMNS],
            show="tree headings", bootstyle="info")
        # 第一列（#0）留给展开箭头，宽度给小一点
        self.tree.column("#0", width=28, stretch=False)
        self.tree.heading("#0", text="")
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            anchor = "w" if key in ("data", "name") else "center"
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "data"))

        vsb = tb.Scrollbar(holder, orient="vertical", command=self.tree.yview,
                           bootstyle="round")
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)

        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<<TreeviewClose>>", self._on_close)

        self.tree.tag_configure("tx", foreground="#1f8fff")
        self.tree.tag_configure("err", foreground="#e74c3c")
        self.tree.tag_configure("signal", foreground="#7a8699")

    # ---------- 模式 ----------

    def _on_mode_change(self):
        self.rebuild()

    def rebuild(self):
        """清空控件并按当前模式与过滤条件重建。"""
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        self._expanded.clear()
        self._scroll_rows = 0
        if self.mode.get() == MODE_FIXED:
            for agg in self.buffer.aggregates():
                self._upsert_fixed(agg)
        else:
            for frame in self.buffer.recent(MAX_SCROLL_ROWS):
                self._append_scroll(frame)

    def clear(self):
        self.buffer.clear()
        self.rebuild()

    # ---------- 工程序列化 ----------

    def to_config(self) -> dict:
        return {"mode": self.mode.get(),
                "filter_id": self.filter_var.get(),
                "autoscroll": self.autoscroll.get()}

    def from_config(self, config) -> None:
        if not isinstance(config, dict):
            return
        if config.get("mode") in (MODE_FIXED, MODE_SCROLL):
            self.mode.set(config["mode"])
        self.filter_var.set(config.get("filter_id", "") or "")
        self.autoscroll.set(bool(config.get("autoscroll", True)))
        self.rebuild()

    # ---------- 刷新（由主窗口定时调用） ----------

    def refresh(self):
        """每个 UI tick 调一次。所有渲染都在这里批量做。"""
        if self.mode.get() == MODE_FIXED:
            for agg in self.buffer.aggregates():
                self._upsert_fixed(agg)
        else:
            frames = self.buffer.drain_pending()
            for frame in frames:
                self._append_scroll(frame)
            if frames and self.autoscroll.get():
                self.tree.yview_moveto(1.0)
            self._trim_scroll()

        if self._expanded:
            self._refresh_expanded()

        pending = self.buffer.pending_count()
        text = f"缓冲 {len(self.buffer):,} 帧 / 共收 {self.buffer.total_received:,}"
        if self.buffer.dropped:
            text += f" / 丢弃 {self.buffer.dropped:,}"
        if pending > 500:
            text += f" / 积压 {pending:,}"
        self.info.configure(text=text)

    # ---------- 固定模式 ----------

    def _passes_filter(self, can_id: int) -> bool:
        text = self.filter_var.get().strip()
        if not text:
            return True
        try:
            wanted = int(text, 16) if text.lower().startswith("0x") else int(text, 16)
        except ValueError:
            return True
        return can_id == wanted

    def _upsert_fixed(self, agg: Aggregate):
        if not self._passes_filter(agg.can_id):
            return
        key = (agg.chn, agg.can_id, agg.ide)
        frame = agg.last
        if frame is None:
            return
        info = self.owner.lookup_message(frame)
        values = (
            f"{agg.last_ts_us / 1e6:.4f}",
            CHN_NAMES.get(agg.chn, str(agg.chn)),
            "Tx" if agg.tx_count else "Rx",
            frame.id_text(),
            info.name if info else "",
            str(len(frame.data)),
            f"{agg.period_ms:.2f}" if agg.period_us else "",
            str(agg.count),
            frame.data_text(),
        )
        iid = self._rows.get(key)
        if iid is None:
            iid = self.tree.insert("", END, values=values,
                                   tags=self._tags(frame))
            self._rows[key] = iid
            if info and info.signals:
                # 占位子节点，让展开箭头出现；真正内容在展开时才填
                self.tree.insert(iid, END, values=("", "", "", "", "…", "", "", "", ""))
        else:
            # 固定模式的关键：只改值，不删不插 —— 这是不卡的原因
            self.tree.item(iid, values=values, tags=self._tags(frame))

    # ---------- 滚动模式 ----------

    def _append_scroll(self, frame):
        if not self._passes_filter(frame.can_id):
            return
        info = self.owner.lookup_message(frame)
        values = (
            f"{frame.ts_us / 1e6:.4f}",
            CHN_NAMES.get(frame.chn, str(frame.chn)),
            frame.direction,
            frame.id_text(),
            info.name if info else "",
            str(len(frame.data)),
            "", "",
            frame.data_text(),
        )
        self.tree.insert("", END, values=values, tags=self._tags(frame))
        self._scroll_rows += 1

    def _trim_scroll(self):
        """超出上限就从头删。Treeview 行数过万会明显迟钝。"""
        if self._scroll_rows <= MAX_SCROLL_ROWS:
            return
        children = self.tree.get_children()
        excess = len(children) - MAX_SCROLL_ROWS
        if excess > 0:
            self.tree.delete(*children[:excess])
            self._scroll_rows -= excess

    # ---------- 信号展开（惰性解码） ----------

    def _on_open(self, _event):
        iid = self.tree.focus()
        if iid:
            self._expanded.add(iid)
            self._fill_signals(iid)

    def _on_close(self, _event):
        iid = self.tree.focus()
        self._expanded.discard(iid)

    def _refresh_expanded(self):
        for iid in list(self._expanded):
            if self.tree.exists(iid):
                self._fill_signals(iid)
            else:
                self._expanded.discard(iid)

    def _fill_signals(self, iid):
        """只对展开的行解码 —— 这就是惰性解码的落点。"""
        key = None
        for candidate, row in self._rows.items():
            if row == iid:
                key = candidate
                break
        if key is None:
            return
        chn, can_id, ide = key
        agg = None
        for item in self.buffer.aggregates():
            if (item.chn, item.can_id, item.ide) == key:
                agg = item
                break
        if agg is None or agg.last is None:
            return

        info, decoded = self.owner.decode_frame(agg.last)
        self.tree.delete(*self.tree.get_children(iid))
        if not info or not decoded:
            self.tree.insert(iid, END,
                             values=("", "", "", "", "（无数据库匹配）", "", "", "", ""),
                             tags=("signal",))
            return
        units = {s.name: s.unit for s in info.signals}
        for name, value in decoded.items():
            if isinstance(value, float):
                shown = f"{value:g}"
            else:
                shown = str(value)
            unit = units.get(name, "")
            self.tree.insert(
                iid, END,
                values=("", "", "", "", name, "", "", "",
                        f"{shown} {unit}".strip()),
                tags=("signal",))

    @staticmethod
    def _tags(frame):
        if frame.err:
            return ("err",)
        if frame.tx:
            return ("tx",)
        return ()
