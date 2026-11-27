#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :signal_page.py
@Description  :信号监控页 —— 仿 CANoe 的 Data 窗口 / TSMaster 的信号面板

从已加载的数据库里挑信号加入监视列表，实时显示物理值。

**只解码被监视的那些报文**，不是全量解码 —— 这是性能的关键。
监视 20 个信号就只解 20 个信号所属的那几条报文，和总线上跑了多少帧无关。
"""
import tkinter as tk
from typing import Dict, List, Optional, Tuple

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y

from BusSpyTool.core.database import MessageInfo, SignalInfo


class WatchItem:
    def __init__(self, message: MessageInfo, signal: SignalInfo):
        self.message = message
        self.signal = signal
        self.value = None
        self.raw = None
        self.updates = 0

    @property
    def key(self) -> Tuple[int, bool, str]:
        return (self.message.frame_id, self.message.is_extended, self.signal.name)


class SignalPage(tb.Frame):
    COLUMNS = (
        ("message", "报文", 190),
        ("id", "ID", 80),
        ("signal", "信号", 220),
        ("value", "值", 120),
        ("unit", "单位", 70),
        ("range", "范围", 140),
        ("updates", "更新次数", 80),
    )

    def __init__(self, master, owner):
        super().__init__(master, padding=6)
        self.owner = owner
        self.items: Dict[str, WatchItem] = {}
        self._build()

    def _build(self):
        bar = tb.Frame(self)
        bar.pack(fill=X, pady=(0, 6))
        tb.Button(bar, text="添加信号…", bootstyle="primary",
                  command=self._add_dialog).pack(side=LEFT, padx=2)
        tb.Button(bar, text="删除选中", bootstyle="danger-outline",
                  command=self._remove_selected).pack(side=LEFT, padx=2)
        tb.Button(bar, text="全部清空", bootstyle="warning-outline",
                  command=self.clear).pack(side=LEFT, padx=2)
        self.hint = tb.Label(bar, bootstyle="secondary",
                             text="只解码被监视的报文，与总线帧率无关")
        self.hint.pack(side=RIGHT)

        holder = tb.Frame(self)
        holder.pack(fill=BOTH, expand=True)
        self.tree = tb.Treeview(holder, columns=[c[0] for c in self.COLUMNS],
                                show="headings", bootstyle="info")
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width,
                             anchor="w" if key in ("message", "signal") else "center")
        vsb = tb.Scrollbar(holder, orient="vertical", command=self.tree.yview,
                           bootstyle="round")
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)

    # ---------- 列表 ----------

    def _add_dialog(self):
        messages = self.owner.databases.all_messages()
        if not messages:
            tk.messagebox.showinfo("没有数据库",
                                   "请先通过「数据库 -> 加载 DBC/ARXML」载入数据库")
            return
        SignalPickDialog(self, messages, self._add_items)

    def _add_items(self, picks: List[Tuple[MessageInfo, SignalInfo]]):
        for message, signal in picks:
            item = WatchItem(message, signal)
            if any(existing.key == item.key for existing in self.items.values()):
                continue
            iid = self.tree.insert("", END, values=(
                message.name, message.id_text(), signal.name,
                "-", signal.unit, signal.range_text, "0"))
            self.items[iid] = item

    def _remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.items.clear()

    # ---------- 工程序列化 ----------

    def to_config(self) -> list:
        return [{"message": item.message.name, "signal": item.signal.name}
                for item in self.items.values()]

    def from_config(self, items) -> None:
        self.clear()
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
            self._add_items(picks)

    # ---------- 刷新 ----------

    def refresh(self):
        if not self.items:
            return
        # 先按报文分组，一条报文只解码一次，供其所有被监视信号共享
        wanted: Dict[Tuple[int, bool], List[str]] = {}
        for iid, item in self.items.items():
            key = (item.message.frame_id, item.message.is_extended)
            wanted.setdefault(key, []).append(iid)

        decoded_cache: Dict[Tuple[int, bool], Optional[dict]] = {}
        for agg in self.owner.buffer.aggregates():
            key = (agg.can_id, agg.ide)
            if key not in wanted or agg.last is None:
                continue
            if key not in decoded_cache:
                _info, decoded = self.owner.decode_frame(agg.last)
                decoded_cache[key] = decoded

        for key, iids in wanted.items():
            decoded = decoded_cache.get(key)
            if not decoded:
                continue
            for iid in iids:
                item = self.items.get(iid)
                if item is None or not self.tree.exists(iid):
                    continue
                value = decoded.get(item.signal.name)
                if value is None:
                    continue
                item.updates += 1
                item.value = value
                shown = f"{value:g}" if isinstance(value, float) else str(value)
                choice = item.signal.choices.get(
                    int(value) if isinstance(value, (int, float)) else None)
                if choice:
                    shown = f"{shown} ({choice})"
                self.tree.set(iid, "value", shown)
                self.tree.set(iid, "updates", str(item.updates))


class SignalPickDialog(tb.Toplevel):
    """两级选择：先挑报文，再勾信号。"""

    def __init__(self, master, messages: List[MessageInfo], on_pick):
        super().__init__(master)
        self.title("添加监视信号")
        self.geometry("760x480")
        self.messages = messages
        self.on_pick = on_pick
        self._current: Optional[MessageInfo] = None

        top = tb.Frame(self, padding=8)
        top.pack(fill=X)
        tb.Label(top, text="搜索报文").pack(side=LEFT)
        self.filter_var = tk.StringVar()
        entry = tb.Entry(top, textvariable=self.filter_var)
        entry.pack(side=LEFT, fill=X, expand=True, padx=6)
        entry.bind("<KeyRelease>", lambda _e: self._reload_messages())

        panes = tb.Frame(self, padding=(8, 0))
        panes.pack(fill=BOTH, expand=True)

        left = tb.Labelframe(panes, text="报文", padding=4)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 4))
        self.msg_list = tk.Listbox(left, exportselection=False)
        self.msg_list.pack(fill=BOTH, expand=True)
        self.msg_list.bind("<<ListboxSelect>>", lambda _e: self._reload_signals())

        right = tb.Labelframe(panes, text="信号（可多选）", padding=4)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=(4, 0))
        self.sig_list = tk.Listbox(right, selectmode="extended", exportselection=False)
        self.sig_list.pack(fill=BOTH, expand=True)

        tb.Button(self, text="添加", bootstyle="primary",
                  command=self._confirm).pack(pady=10)

        self._reload_messages()
        self.transient(master)
        self.grab_set()

    def _reload_messages(self):
        text = self.filter_var.get().lower()
        self.msg_list.delete(0, END)
        self._shown = []
        for info in self.messages:
            if text and text not in info.name.lower() and text not in info.id_text().lower():
                continue
            self.msg_list.insert(END, f"{info.id_text()}  {info.name}")
            self._shown.append(info)
            if len(self._shown) >= 2000:
                break

    def _reload_signals(self):
        selection = self.msg_list.curselection()
        self.sig_list.delete(0, END)
        if not selection:
            self._current = None
            return
        self._current = self._shown[selection[0]]
        for signal in self._current.signals:
            unit = f"  [{signal.unit}]" if signal.unit else ""
            self.sig_list.insert(END, f"{signal.name}{unit}")

    def _confirm(self):
        if self._current is None:
            return
        picks = [(self._current, self._current.signals[i])
                 for i in self.sig_list.curselection()]
        if picks:
            self.on_pick(picks)
        self.destroy()
