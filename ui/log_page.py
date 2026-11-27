#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :log_page.py
@Description  :日志页。把 logger 的输出接到界面上。

用 logging.Handler 转发到 Tk 文本框，但**不在日志线程里直接碰控件** ——
Tk 不是线程安全的，接收线程打的日志若直接 insert 会随机崩溃。
统一走队列，由 UI 线程 after() 消费。
"""
import logging
import queue
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y

from BusSpyTool.utils.logger import logger

MAX_LINES = 2000


class _QueueHandler(logging.Handler):
    def __init__(self, sink: queue.Queue):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        try:
            self.sink.put_nowait((record.levelno, self.format(record)))
        except queue.Full:
            pass


class LogPage(tb.Frame):
    def __init__(self, master, owner):
        super().__init__(master, padding=6)
        self.owner = owner
        self._queue: queue.Queue = queue.Queue(maxsize=4000)
        self._build()
        self._attach()

    def _build(self):
        bar = tb.Frame(self)
        bar.pack(fill=X, pady=(0, 6))
        self.autoscroll = tk.BooleanVar(value=True)
        tb.Checkbutton(bar, text="自动滚动", variable=self.autoscroll,
                       bootstyle="round-toggle").pack(side=LEFT)
        tb.Button(bar, text="清空", bootstyle="warning-outline",
                  command=self.clear).pack(side=RIGHT)

        holder = tb.Frame(self)
        holder.pack(fill=BOTH, expand=True)
        self.text = tk.Text(holder, wrap="none", height=10, undo=False)
        vsb = tb.Scrollbar(holder, orient="vertical", command=self.text.yview,
                           bootstyle="round")
        self.text.configure(yscrollcommand=vsb.set, state="disabled")
        vsb.pack(side=RIGHT, fill=Y)
        self.text.pack(side=LEFT, fill=BOTH, expand=True)

        self.text.tag_configure("WARNING", foreground="#e39b1c")
        self.text.tag_configure("ERROR", foreground="#e74c3c")

    def _attach(self):
        handler = _QueueHandler(self._queue)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)

    def refresh(self):
        """UI tick 调用，批量把队列里的日志刷进文本框。"""
        lines = []
        while True:
            try:
                lines.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not lines:
            return
        self.text.configure(state="normal")
        for levelno, text in lines:
            tag = ("ERROR" if levelno >= logging.ERROR
                   else "WARNING" if levelno >= logging.WARNING else "")
            self.text.insert(END, text + "\n", tag)
        # 超出上限就从头删，否则长时间运行会吃内存
        total = int(self.text.index("end-1c").split(".")[0])
        if total > MAX_LINES:
            self.text.delete("1.0", f"{total - MAX_LINES}.0")
        self.text.configure(state="disabled")
        if self.autoscroll.get():
            self.text.see(END)

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", END)
        self.text.configure(state="disabled")
