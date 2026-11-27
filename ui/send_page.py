#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :send_page.py
@Description  :发送页 —— 仿 CANoe 的 Interactive Generator / TSMaster 发送面板

单帧发送与周期发送。**周期发送下发到固件本地调度**，不是上位机定时器 ——
上位机只负责下发槽位，固件按绝对时基发，抖动 ±50us 量级。这是本工具
相对「PC 软件定时发」的根本差别。

可以直接填 hex 数据，也可以从已加载的数据库里挑报文自动带出长度与名称。
"""
import tkinter as tk
from tkinter import messagebox
from typing import Dict, Optional

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y

from BusSpyTool.core.bstp import Chn, Frame
from BusSpyTool.ui.trace_page import CHN_NAMES


class SendEntry:
    """发送列表里的一行。slot_id 非 None 表示周期已在固件上跑着。

    name 是用户给这条的业务名字（「写 VIN」「唤醒帧」「刷 CCP」）——
    工具不认识这些业务含义，它只负责把这条报文按配置发出去。
    """

    def __init__(self, frame: Frame, period_ms: float = 0.0, name: str = ""):
        self.frame = frame
        self.period_ms = period_ms
        self.name = name
        self.slot_id: Optional[int] = None
        self.sent = 0

    @property
    def running(self) -> bool:
        return self.slot_id is not None

    def to_config(self) -> dict:
        frame = self.frame
        return {
            "name": self.name,
            "chn": frame.chn,
            "id": f"0x{frame.can_id:X}",
            "ext": frame.ide,
            "fd": frame.fd,
            "brs": frame.brs,
            "data": frame.data_text(),
            "period_ms": self.period_ms,
        }

    @classmethod
    def from_config(cls, item: dict) -> "SendEntry":
        text = str(item.get("data", "")).replace(",", " ").strip()
        try:
            data = bytes(int(p, 16) for p in text.split()) if text else b""
        except ValueError:
            data = b""
        frame = Frame(
            can_id=int(str(item.get("id", "0")), 16),
            data=data,
            chn=int(item.get("chn", Chn.CANFD)),
            fd=bool(item.get("fd", False)),
            brs=bool(item.get("brs", False)),
            ide=bool(item.get("ext", False)),
            tx=True)
        return cls(frame, float(item.get("period_ms", 0) or 0),
                   str(item.get("name", "")))


class SendPage(tb.Frame):
    COLUMNS = (
        ("name", "名称", 150),
        ("state", "状态", 58),
        ("chn", "通道", 70),
        ("id", "ID", 86),
        ("type", "类型", 88),
        ("dlc", "长度", 50),
        ("period", "周期ms", 70),
        ("data", "数据", 380),
    )

    def __init__(self, master, owner):
        super().__init__(master, padding=6)
        self.owner = owner
        self.entries: Dict[str, SendEntry] = {}
        self._build()

    def _build(self):
        editor = tb.Labelframe(self, text="报文编辑", padding=8)
        editor.pack(fill=X, pady=(0, 6))

        row = tb.Frame(editor)
        row.pack(fill=X)

        tb.Label(row, text="通道").pack(side=LEFT)
        self.chn_var = tk.StringVar(value=CHN_NAMES[Chn.CANFD])
        tb.Combobox(row, textvariable=self.chn_var, width=8, state="readonly",
                    values=[CHN_NAMES[Chn.CANFD], CHN_NAMES[Chn.TWAI],
                            CHN_NAMES[Chn.ETH]]).pack(side=LEFT, padx=(4, 12))

        tb.Label(row, text="ID(hex)").pack(side=LEFT)
        self.id_var = tk.StringVar(value="123")
        tb.Entry(row, textvariable=self.id_var, width=10).pack(side=LEFT, padx=(4, 12))

        self.ext_var = tk.BooleanVar(value=False)
        tb.Checkbutton(row, text="扩展帧", variable=self.ext_var).pack(side=LEFT, padx=4)
        self.fd_var = tk.BooleanVar(value=True)
        tb.Checkbutton(row, text="FD", variable=self.fd_var).pack(side=LEFT, padx=4)
        self.brs_var = tk.BooleanVar(value=True)
        tb.Checkbutton(row, text="BRS", variable=self.brs_var).pack(side=LEFT, padx=4)

        tb.Label(row, text="周期ms").pack(side=LEFT, padx=(12, 0))
        self.period_var = tk.StringVar(value="0")
        tb.Entry(row, textvariable=self.period_var, width=8).pack(side=LEFT, padx=4)

        row2 = tb.Frame(editor)
        row2.pack(fill=X, pady=(8, 0))
        tb.Label(row2, text="名称").pack(side=LEFT)
        self.name_var = tk.StringVar()
        tb.Entry(row2, textvariable=self.name_var, width=18).pack(side=LEFT, padx=(4, 12))
        tb.Label(row2, text="数据(hex)").pack(side=LEFT)
        self.data_var = tk.StringVar(value="00 11 22 33 44 55 66 77")
        tb.Entry(row2, textvariable=self.data_var).pack(side=LEFT, fill=X,
                                                        expand=True, padx=(4, 12))
        tb.Button(row2, text="从数据库选…", bootstyle="secondary-outline",
                  command=self._pick_from_db).pack(side=LEFT, padx=2)

        row3 = tb.Frame(editor)
        row3.pack(fill=X, pady=(8, 0))
        tb.Button(row3, text="加入列表", bootstyle="primary",
                  command=self._add_entry).pack(side=LEFT, padx=2)
        tb.Button(row3, text="立即发送一次", bootstyle="success",
                  command=self._send_once_from_editor).pack(side=LEFT, padx=2)

        listbox = tb.Labelframe(self, text="发送列表（周期发送由固件本地调度）",
                                padding=6)
        listbox.pack(fill=BOTH, expand=True)

        bar = tb.Frame(listbox)
        bar.pack(fill=X, pady=(0, 6))
        tb.Button(bar, text="发送选中", bootstyle="success-outline",
                  command=self._send_selected).pack(side=LEFT, padx=2)
        tb.Button(bar, text="启动周期", bootstyle="info-outline",
                  command=self._start_selected).pack(side=LEFT, padx=2)
        tb.Button(bar, text="停止周期", bootstyle="warning-outline",
                  command=self._stop_selected).pack(side=LEFT, padx=2)
        tb.Button(bar, text="全部启动", bootstyle="info-outline",
                  command=lambda: self._bulk(True)).pack(side=LEFT, padx=(12, 2))
        tb.Button(bar, text="全部停止", bootstyle="warning-outline",
                  command=lambda: self._bulk(False)).pack(side=LEFT, padx=2)
        tb.Button(bar, text="删除选中", bootstyle="danger-outline",
                  command=self._remove_selected).pack(side=RIGHT, padx=2)

        holder = tb.Frame(listbox)
        holder.pack(fill=BOTH, expand=True)
        self.tree = tb.Treeview(holder, columns=[c[0] for c in self.COLUMNS],
                                show="headings", bootstyle="info")
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width,
                             anchor="w" if key in ("data", "comment") else "center",
                             stretch=(key == "data"))
        vsb = tb.Scrollbar(holder, orient="vertical", command=self.tree.yview,
                           bootstyle="round")
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.tree.tag_configure("running", foreground="#2ecc71")
        self.tree.bind("<Double-1>", lambda _e: self._send_selected())

    # ---------- 编辑区 ----------

    def _chn_value(self) -> int:
        for key, name in CHN_NAMES.items():
            if name == self.chn_var.get():
                return key
        return Chn.CANFD

    def _parse_data(self) -> Optional[bytes]:
        text = self.data_var.get().replace(",", " ").strip()
        if not text:
            return b""
        try:
            parts = text.split()
            if len(parts) == 1 and len(parts[0]) > 2:
                raw = bytes.fromhex(parts[0])
            else:
                raw = bytes(int(p, 16) for p in parts)
        except ValueError:
            messagebox.showerror("数据格式错误",
                                 "数据应为十六进制，如 00 11 22 或 001122")
            return None
        if len(raw) > 64:
            messagebox.showerror("数据过长", f"CAN-FD 最多 64 字节，给了 {len(raw)}")
            return None
        return raw

    def _build_frame(self) -> Optional[Frame]:
        data = self._parse_data()
        if data is None:
            return None
        try:
            can_id = int(self.id_var.get().strip(), 16)
        except ValueError:
            messagebox.showerror("ID 格式错误", "ID 应为十六进制，如 123 或 1A0")
            return None
        return Frame(
            can_id=can_id, data=data, chn=self._chn_value(),
            fd=self.fd_var.get(), brs=self.brs_var.get() and self.fd_var.get(),
            ide=self.ext_var.get(), tx=True)

    def _pick_from_db(self):
        messages = self.owner.databases.all_messages()
        if not messages:
            messagebox.showinfo("没有数据库",
                                "请先通过「数据库 -> 加载 DBC/ARXML」载入数据库")
            return
        PickDialog(self, messages, self._apply_picked)

    def _apply_picked(self, info):
        self.id_var.set(f"{info.frame_id:X}")
        self.ext_var.set(info.is_extended)
        self.fd_var.set(info.is_fd or info.length > 8)
        self.data_var.set(" ".join("00" for _ in range(max(1, info.length))))
        if not self.name_var.get().strip():
            self.name_var.set(info.name)
        if info.cycle_ms:
            self.period_var.set(f"{info.cycle_ms:g}")

    # ---------- 列表操作 ----------

    def _add_entry(self):
        frame = self._build_frame()
        if frame is None:
            return
        try:
            period = float(self.period_var.get() or 0)
        except ValueError:
            period = 0.0
        name = self.name_var.get().strip()
        if not name:
            # 没起名就用数据库里的报文名兜底，再不行用 ID
            info = self.owner.lookup_message(frame)
            name = info.name if info else frame.id_text()
        entry = SendEntry(frame, period, name)
        iid = self.tree.insert("", END, values=self._values(entry))
        self.entries[iid] = entry
        self.owner.mark_project_dirty()

    # ---------- 工程序列化 ----------

    def to_config(self) -> list:
        return [self.entries[iid].to_config()
                for iid in self.tree.get_children() if iid in self.entries]

    def from_config(self, items) -> None:
        self._bulk(False)
        self.tree.delete(*self.tree.get_children())
        self.entries.clear()
        for item in items or []:
            try:
                entry = SendEntry.from_config(item)
            except (ValueError, TypeError):
                continue
            iid = self.tree.insert("", END, values=self._values(entry))
            self.entries[iid] = entry

    def _values(self, entry: SendEntry):
        frame = entry.frame
        kind = "CAN-FD" if frame.fd else "CAN"
        if frame.fd and frame.brs:
            kind += "+BRS"
        return (
            entry.name,
            "运行中" if entry.running else "停止",
            CHN_NAMES.get(frame.chn, str(frame.chn)),
            frame.id_text(),
            kind,
            str(len(frame.data)),
            f"{entry.period_ms:g}" if entry.period_ms else "",
            frame.data_text(),
        )

    def _refresh_row(self, iid):
        entry = self.entries[iid]
        self.tree.item(iid, values=self._values(entry),
                       tags=("running",) if entry.running else ())

    def _selected(self):
        return [iid for iid in self.tree.selection() if iid in self.entries]

    def _send_once_from_editor(self):
        frame = self._build_frame()
        if frame is None:
            return
        if not self.owner.require_device():
            return
        self.owner.device.send_frame(frame)

    def _send_selected(self):
        if not self.owner.require_device():
            return
        frames = [self.entries[iid].frame for iid in self._selected()]
        if frames:
            self.owner.device.send_frames(frames)

    def _start_selected(self):
        if not self.owner.require_device():
            return
        for iid in self._selected():
            self._start(iid)

    def _start(self, iid):
        entry = self.entries[iid]
        if entry.running or entry.period_ms <= 0:
            return
        slot = self.owner.device.add_cyc(entry.frame,
                                         int(entry.period_ms * 1000))
        entry.slot_id = slot
        self._refresh_row(iid)

    def _stop_selected(self):
        for iid in self._selected():
            self._stop(iid)

    def _stop(self, iid):
        entry = self.entries[iid]
        if not entry.running:
            return
        if self.owner.device:
            self.owner.device.remove_cyc(entry.slot_id)
        entry.slot_id = None
        self._refresh_row(iid)

    def _bulk(self, start: bool):
        if start and not self.owner.require_device():
            return
        for iid in list(self.entries):
            self._start(iid) if start else self._stop(iid)

    def _remove_selected(self):
        for iid in self._selected():
            self._stop(iid)
            self.tree.delete(iid)
            self.entries.pop(iid, None)
        self.owner.mark_project_dirty()

    def on_disconnect(self):
        """断开时固件侧的槽位已失效，本地状态要跟着复位。"""
        for iid, entry in self.entries.items():
            entry.slot_id = None
            self._refresh_row(iid)


class PickDialog(tb.Toplevel):
    """从已加载数据库里挑一条报文。"""

    def __init__(self, master, messages, on_pick):
        super().__init__(master)
        self.title("选择报文")
        self.on_pick = on_pick
        self.messages = messages
        self.geometry("560x420")

        self.filter_var = tk.StringVar()
        bar = tb.Frame(self, padding=8)
        bar.pack(fill=X)
        tb.Label(bar, text="搜索").pack(side=LEFT)
        entry = tb.Entry(bar, textvariable=self.filter_var)
        entry.pack(side=LEFT, fill=X, expand=True, padx=6)
        entry.bind("<KeyRelease>", lambda _e: self._reload())

        self.tree = tb.Treeview(self, columns=("id", "name", "dlc", "cycle"),
                                show="headings", bootstyle="info")
        for key, title, width in (("id", "ID", 90), ("name", "名称", 260),
                                  ("dlc", "长度", 60), ("cycle", "周期ms", 80)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width,
                             anchor="w" if key == "name" else "center")
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=6)
        self.tree.bind("<Double-1>", lambda _e: self._choose())

        tb.Button(self, text="选择", bootstyle="primary",
                  command=self._choose).pack(pady=(0, 10))
        self._reload()
        self.transient(master)
        self.grab_set()

    def _reload(self):
        text = self.filter_var.get().lower()
        self.tree.delete(*self.tree.get_children())
        self._shown = []
        for info in self.messages:
            if text and text not in info.name.lower() and text not in info.id_text().lower():
                continue
            self.tree.insert("", END, values=(
                info.id_text(), info.name, info.length,
                f"{info.cycle_ms:g}" if info.cycle_ms else ""))
            self._shown.append(info)
            if len(self._shown) >= 2000:
                break

    def _choose(self):
        selection = self.tree.selection()
        if not selection:
            return
        index = self.tree.index(selection[0])
        if 0 <= index < len(self._shown):
            self.on_pick(self._shown[index])
        self.destroy()
