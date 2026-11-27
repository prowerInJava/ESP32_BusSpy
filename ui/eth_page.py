#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :eth_page.py
@Description  :以太网页 —— ESP32 经 W5500 与 ADCU 直接收发以太网信号

定位要分清，这里**不是**上位机与设备之间的管理链路：

    电脑 --USB CDC--> ESP32 --W5500--> ADCU 被测以太网
         (BSTP 管理)         (本页管的就是这一段)

W5500 专用于被测网络，上位机走 USB，两者互不干扰。设备在被测网段上
是一个**独立节点**，自己收发 SOME/IP 消息与 arxml 定长裸 UDP 帧，
不依赖电脑转发。

当前固件尚未实现这部分（设计方案第 6 节，P5 阶段），本页先把配置面
与交互流程定下来，固件就绪后接上即可。
"""
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, W, X, Y


class EthPage(tb.Frame):
    def __init__(self, master, owner):
        super().__init__(master, padding=8)
        self.owner = owner
        self._build()

    def _build(self):
        notice = tb.Label(
            self, bootstyle="warning",
            text=("W5500 专用于被测以太网（接 ADCU）。上位机连接走 USB CDC，"
                  "两条网络互不干扰。\n当前固件未实现本页功能，界面与流程先行。"))
        notice.pack(fill=X, pady=(0, 8), anchor=W)

        config = tb.Labelframe(self, text="设备以太网口（W5500）", padding=10)
        config.pack(fill=X, pady=(0, 8))

        grid = tb.Frame(config)
        grid.pack(fill=X)
        self.vars = {}
        fields = (("ip", "IP 地址", "192.168.2.100"),
                  ("mask", "子网掩码", "255.255.255.0"),
                  ("gw", "网关", "192.168.2.1"),
                  ("mac", "MAC", "02:00:5B:00:00:01"))
        for index, (key, title, default) in enumerate(fields):
            tb.Label(grid, text=title, width=10, anchor=W).grid(
                row=index // 2, column=(index % 2) * 2, sticky=W, pady=3, padx=(0, 4))
            var = tk.StringVar(value=default)
            self.vars[key] = var
            tb.Entry(grid, textvariable=var, width=20).grid(
                row=index // 2, column=(index % 2) * 2 + 1, sticky=W, pady=3, padx=(0, 20))

        buttons = tb.Frame(config)
        buttons.pack(fill=X, pady=(8, 0))
        tb.Button(buttons, text="下发配置", bootstyle="primary",
                  state="disabled").pack(side=LEFT, padx=2)
        tb.Button(buttons, text="读取当前", bootstyle="secondary-outline",
                  state="disabled").pack(side=LEFT, padx=2)
        self.link_label = tb.Label(buttons, text="链路：未知", bootstyle="secondary")
        self.link_label.pack(side=RIGHT)

        tabs = tb.Notebook(self, bootstyle="info")
        tabs.pack(fill=BOTH, expand=True)
        tabs.add(self._build_udp(tabs), text="裸 UDP 帧")
        tabs.add(self._build_someip(tabs), text="SOME/IP")

    def _build_udp(self, master):
        page = tb.Frame(master, padding=8)
        tb.Label(page, anchor=W, justify="left", bootstyle="secondary",
                 text=("对接 arxml 生成的定长 UDP 帧（PDU）。周期发送复用 CAN 那套"
                       "固件周期引擎，\n两种总线共用同一个时间基准 —— 跨总线的端到端"
                       "时延比对才有意义。")).pack(fill=X, pady=(0, 8))

        bar = tb.Frame(page)
        bar.pack(fill=X, pady=(0, 6))
        tb.Button(bar, text="加载 PDU 定义…", bootstyle="primary",
                  state="disabled").pack(side=LEFT, padx=2)
        tb.Button(bar, text="添加发送", bootstyle="secondary-outline",
                  state="disabled").pack(side=LEFT, padx=2)

        columns = (("dir", "方向", 60), ("name", "PDU 名称", 220),
                   ("peer", "对端", 180), ("port", "端口", 70),
                   ("len", "长度", 60), ("period", "周期ms", 80),
                   ("count", "计数", 70))
        tree = tb.Treeview(page, columns=[c[0] for c in columns],
                           show="headings", bootstyle="info")
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width,
                        anchor="w" if key in ("name", "peer") else "center")
        tree.pack(fill=BOTH, expand=True)
        self.udp_tree = tree
        return page

    def _build_someip(self, master):
        page = tb.Frame(master, padding=8)
        tb.Label(page, anchor=W, justify="left", bootstyle="secondary",
                 text=("设备作为被测网段上的 SOME/IP 端点：OfferService / "
                       "FindService 响应 /\nSubscribe + SubscribeAck / Notify。"
                       "SD 走多播 224.244.224.245:30490。\n"
                       "不做 TCP 传输与 SOME/IP-TP 分段。")).pack(fill=X, pady=(0, 8))

        bar = tb.Frame(page)
        bar.pack(fill=X, pady=(0, 6))
        tb.Button(bar, text="加载服务定义…", bootstyle="primary",
                  state="disabled").pack(side=LEFT, padx=2)
        tb.Button(bar, text="Offer 服务", bootstyle="success-outline",
                  state="disabled").pack(side=LEFT, padx=2)
        tb.Button(bar, text="订阅事件组", bootstyle="info-outline",
                  state="disabled").pack(side=LEFT, padx=2)

        columns = (("service", "Service ID", 90), ("instance", "Instance", 80),
                   ("kind", "类型", 110), ("id", "Method/Event", 110),
                   ("state", "状态", 90), ("count", "计数", 70))
        tree = tb.Treeview(page, columns=[c[0] for c in columns],
                           show="headings", bootstyle="info")
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="center")
        tree.pack(fill=BOTH, expand=True)
        self.someip_tree = tree
        return page

    def refresh(self):
        device = self.owner.device
        if device is None:
            self.link_label.configure(text="链路：未连接", bootstyle="secondary")
            return
        up = getattr(device.stat, "link_up", False)
        self.link_label.configure(
            text="链路：已连接" if up else "链路：断开",
            bootstyle="success" if up else "danger")
