#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :main_window.py
@Description  :主窗口 —— 仿 CANoe / TSMaster 的整体布局

    菜单条（窗口内 Menubutton，不是原生菜单栏）
    工具栏（连接方式 / 连接 / 采集控制）
    左：数据库树      右：Trace / 发送 / 信号 / 统计 / 以太网 / 日志
    状态栏

菜单条刻意不用 self.configure(menu=...)：原生菜单栏在 Windows 上由系统
绘制，Tk 的配色它不认，切深色主题会留一条白边。

UI 刷新统一在一个 tick 里批量做（REFRESH_MS），**不在接收线程碰控件** ——
Tk 不是线程安全的。core 层的 listener 只往 TraceBuffer 里塞数据。
"""
import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, W, X, Y

from BusSpyTool import paths
from BusSpyTool.config import app_meta
from BusSpyTool.core.database import SUPPORTED_SUFFIXES, DatabaseManager
from BusSpyTool.core.device import Device
from BusSpyTool.core.mock import MockDevice
from BusSpyTool.core.project import PROJECT_SUFFIX, Project
from BusSpyTool.core.tracebuf import TraceBuffer
from BusSpyTool.core.transport import SerialTransport
from BusSpyTool.ui import (apply_titlebar_mode, apply_window_icon,
                           show_centered, style_menus)
from BusSpyTool.ui.eth_page import EthPage
from BusSpyTool.ui.graph_page import GraphPage
from BusSpyTool.ui.log_page import LogPage
from BusSpyTool.ui.send_page import SendPage
from BusSpyTool.ui.signal_page import SignalPage
from BusSpyTool.ui.stat_page import StatPage
from BusSpyTool.ui.trace_page import TracePage
from BusSpyTool.utils.logger import logger

REFRESH_MS = 100          # UI tick。10 Hz 足够人眼，又能把渲染成本摊薄
DEFAULT_THEME = "litera"

LIGHT_THEMES = ("litera", "cosmo", "flatly", "journal", "lumen", "minty",
                "pulse", "sandstone", "united", "yeti", "morph", "simplex")
DARK_THEMES = ("darkly", "cyborg", "superhero", "solar", "vapor")

CONN_USB = "USB (CDC)"
CONN_UDP = "网络 (UDP)"
CONN_MOCK = "模拟设备"


class MainWindow(tb.Window):
    def __init__(self):
        self.settings = self._load_settings()
        # 不能在 super().__init__ 之前碰 self.style —— 那时它还是 None。
        # 直接拿已知主题名校验，菜单里也只提供这些。
        theme = self.settings.get("theme", DEFAULT_THEME)
        if theme not in LIGHT_THEMES + DARK_THEMES:
            theme = DEFAULT_THEME
        super().__init__(themename=theme)
        self.withdraw()            # 先藏起来，搭完再定位显示，避免闪烁

        self.title(app_meta.DEVICE_NAME)
        self.minsize(1100, 680)
        self.bind_all("<Control-s>", lambda _e: self._save_project())
        self.bind_all("<Control-o>", lambda _e: self._open_project())

        self.buffer = TraceBuffer()
        self.databases = DatabaseManager()
        self.device = None
        self._pages = {}
        # 页面在 _build() 里创建时就会注册/标脏，必须先于 _build 初始化
        self._frame_listeners = []
        self.project = Project()
        self._loading_project = False

        try:
            self._build()
            apply_window_icon(self)
            self._apply_chrome()
            self._update_title()
        finally:
            geometry = self.settings.get("window_geometry")
            if geometry:
                try:
                    self.geometry(geometry)
                    self.deiconify()
                except tk.TclError:
                    show_centered(self, 1280, 800)
            else:
                show_centered(self, 1280, 800)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(REFRESH_MS, self._tick)

    # ---------- 布局 ----------

    def _build(self):
        self._build_menubar()
        self._build_toolbar()

        body = tb.Panedwindow(self, orient="horizontal")
        body.pack(fill=BOTH, expand=True, padx=8, pady=(0, 4))

        left = tb.Labelframe(body, text="数据库", padding=4)
        self._build_db_tree(left)
        body.add(left, weight=1)

        right = tb.Frame(body)
        self.notebook = tb.Notebook(right, bootstyle="info")
        self.notebook.pack(fill=BOTH, expand=True)
        for key, title, factory in (
                ("trace", "Trace", TracePage),
                ("graph", "波形", GraphPage),
                ("send", "发送", SendPage),
                ("signal", "信号", SignalPage),
                ("stat", "统计", StatPage),
                ("eth", "以太网", EthPage),
                ("log", "日志", LogPage)):
            page = factory(self.notebook, self)
            self.notebook.add(page, text=title)
            self._pages[key] = page
        body.add(right, weight=4)

        self._build_statusbar()

    def _build_menubar(self):
        bar = tb.Frame(self, padding=(6, 3))
        bar.pack(fill=X)
        self._menus = []

        file_menu = self._add_menu(bar, "文件")
        file_menu.add_command(label="新建工程", command=self._new_project)
        file_menu.add_command(label="打开工程…", command=self._open_project)
        file_menu.add_command(label="保存工程", command=self._save_project)
        file_menu.add_command(label="工程另存为…", command=self._save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="导出 Trace 为 CSV…", command=self._export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)

        db_menu = self._add_menu(bar, "数据库")
        db_menu.add_command(label="加载 DBC / ARXML…", command=self._load_database)
        db_menu.add_command(label="移除选中", command=self._remove_database)
        db_menu.add_command(label="全部卸载", command=self._clear_databases)

        dev_menu = self._add_menu(bar, "设备")
        dev_menu.add_command(label="连接", command=self.connect)
        dev_menu.add_command(label="断开", command=self.disconnect)
        dev_menu.add_separator()
        dev_menu.add_command(label="Bus On", command=lambda: self._bus(True))
        dev_menu.add_command(label="Bus Off", command=lambda: self._bus(False))
        dev_menu.add_command(label="复位设备", command=self._reset_device)

        theme_menu = self._add_menu(bar, "主题")
        self.theme_var = tk.StringVar(value=self.style.theme.name)
        light = tk.Menu(theme_menu, tearoff=0)
        dark = tk.Menu(theme_menu, tearoff=0)
        available = set(self.style.theme_names())
        for name in LIGHT_THEMES:
            if name in available:
                light.add_radiobutton(label=name, value=name,
                                      variable=self.theme_var,
                                      command=self._on_theme_change)
        for name in DARK_THEMES:
            if name in available:
                dark.add_radiobutton(label=name, value=name,
                                     variable=self.theme_var,
                                     command=self._on_theme_change)
        theme_menu.add_cascade(label="浅色", menu=light)
        theme_menu.add_cascade(label="深色", menu=dark)
        self._menus.extend([light, dark])

        help_menu = self._add_menu(bar, "帮助")
        help_menu.add_command(label="关于", command=self._about)

    def _add_menu(self, parent, text):
        # Menubutton 不支持 "link"（那是 Button 的），用 light 做扁平菜单栏效果。
        # padding 压小，否则菜单条会占掉 50+ 像素高
        button = tb.Menubutton(parent, text=text, bootstyle="light", padding=(10, 2))
        button.pack(side=LEFT, padx=1)
        menu = tk.Menu(button, tearoff=0)
        button["menu"] = menu
        self._menus.append(menu)
        return menu

    def _build_toolbar(self):
        bar = tb.Frame(self, padding=(8, 4))
        bar.pack(fill=X)

        tb.Label(bar, text="连接方式").pack(side=LEFT, padx=(0, 4))
        self.conn_mode = tk.StringVar(value=self.settings.get("conn_mode", CONN_USB))
        combo = tb.Combobox(bar, textvariable=self.conn_mode, width=12,
                            state="readonly",
                            values=[CONN_USB, CONN_UDP, CONN_MOCK])
        combo.pack(side=LEFT)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_conn_mode())

        self.target_var = tk.StringVar(value=self.settings.get("target", ""))
        self.target_combo = tb.Combobox(bar, textvariable=self.target_var, width=22)
        self.target_combo.pack(side=LEFT, padx=6)
        tb.Button(bar, text="刷新", bootstyle="secondary-outline", width=4,
                  command=self._refresh_targets).pack(side=LEFT)

        tb.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=10)
        self.connect_btn = tb.Button(bar, text="连接", bootstyle="success",
                                     command=self.connect)
        self.connect_btn.pack(side=LEFT, padx=2)
        self.disconnect_btn = tb.Button(bar, text="断开", bootstyle="danger-outline",
                                        command=self.disconnect, state="disabled")
        self.disconnect_btn.pack(side=LEFT, padx=2)

        tb.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=10)
        self.pause_var = tk.BooleanVar(value=False)
        tb.Checkbutton(bar, text="暂停采集", variable=self.pause_var,
                       command=self._on_pause,
                       bootstyle="round-toggle").pack(side=LEFT, padx=4)
        tb.Button(bar, text="清空", bootstyle="warning-outline",
                  command=self._clear_all).pack(side=LEFT, padx=4)

        self._refresh_targets()
        self._on_conn_mode()

    def _build_db_tree(self, parent):
        self.db_tree = tb.Treeview(parent, show="tree", bootstyle="info")
        vsb = tb.Scrollbar(parent, orient="vertical",
                           command=self.db_tree.yview, bootstyle="round")
        self.db_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.db_tree.pack(side=LEFT, fill=BOTH, expand=True)

    def _build_statusbar(self):
        bar = tb.Frame(self, padding=(10, 4))
        bar.pack(fill=X)
        self.status_conn = tb.Label(bar, text="未连接", bootstyle="secondary")
        self.status_conn.pack(side=LEFT)
        self._sep(bar)
        self.status_load = tb.Label(bar, text="负载 -", bootstyle="secondary")
        self.status_load.pack(side=LEFT)
        self._sep(bar)
        self.status_frames = tb.Label(bar, text="Rx 0  Tx 0", bootstyle="secondary")
        self.status_frames.pack(side=LEFT)
        self._sep(bar)
        self.status_err = tb.Label(bar, text="-", bootstyle="secondary")
        self.status_err.pack(side=LEFT)
        self.status_db = tb.Label(bar, text="无数据库", bootstyle="secondary")
        self.status_db.pack(side=RIGHT)

    @staticmethod
    def _sep(parent):
        tb.Separator(parent, orient="vertical").pack(side=LEFT, fill=Y, padx=10)

    # ---------- 连接 ----------

    def _on_conn_mode(self):
        mode = self.conn_mode.get()
        if mode == CONN_MOCK:
            self.target_combo.configure(state="disabled")
            self.target_var.set("内置模拟器（无需硬件）")
        else:
            self.target_combo.configure(state="normal")
            self._refresh_targets()

    def _refresh_targets(self):
        mode = self.conn_mode.get()
        if mode == CONN_USB:
            candidates = SerialTransport.list_candidates()
            values = [f"{dev}" for dev, _text in candidates]
            self.target_combo.configure(values=values)
            if values and not self.target_var.get().startswith(("COM", "/dev")):
                self.target_var.set(values[0])
            if not values:
                self.target_var.set("")
        elif mode == CONN_UDP:
            self.target_combo.configure(values=["192.168.1.50:8000"])
            if ":" not in self.target_var.get():
                self.target_var.set("192.168.1.50:8000")

    def connect(self):
        if self.device is not None:
            return
        mode = self.conn_mode.get()
        try:
            if mode == CONN_MOCK:
                device = MockDevice(frame_rate=400)
            elif mode == CONN_USB:
                port = self.target_var.get().strip()
                if not port:
                    messagebox.showwarning("没有串口",
                                           "未找到 ESP32 设备。请插好 USB 后点「刷新」。")
                    return
                device = Device.over_usb(port)
            else:
                target = self.target_var.get().strip()
                host, _, port_text = target.partition(":")
                device = Device.over_udp(host, int(port_text or 8000))
        except ValueError as error:
            messagebox.showerror("连接参数错误", str(error))
            return

        device.add_listener(self.buffer.extend)
        for callback in self._frame_listeners:
            device.add_listener(callback)
        if not device.connect():
            messagebox.showerror("连接失败", "无法打开链路，详见日志页")
            return

        self.device = device
        self.connect_btn.configure(state="disabled")
        self.disconnect_btn.configure(state="normal")
        self.status_conn.configure(text=f"已连接  {self._device_text()}",
                                   bootstyle="success")

    def disconnect(self):
        if self.device is None:
            return
        self.device.disconnect()
        self.device = None
        self._pages["send"].on_disconnect()
        self.connect_btn.configure(state="normal")
        self.disconnect_btn.configure(state="disabled")
        self.status_conn.configure(text="未连接", bootstyle="secondary")

    def _device_text(self):
        if self.device is None:
            return "-"
        if isinstance(self.device, MockDevice):
            return "模拟设备"
        return self.device.description

    def require_device(self) -> bool:
        if self.device is None:
            messagebox.showwarning("未连接", "请先连接设备（可先用「模拟设备」试界面）")
            return False
        return True

    def _bus(self, on: bool):
        if self.require_device():
            self.device.bus_on() if on else self.device.bus_off()

    def _reset_device(self):
        if self.require_device():
            self.device.reset()

    # ---------- 数据库 ----------

    def _load_database(self):
        filenames = filedialog.askopenfilenames(
            title="加载 CAN 数据库",
            filetypes=[("CAN 数据库", "*.dbc *.arxml *.kcd *.sym"),
                       ("DBC", "*.dbc"), ("ARXML", "*.arxml"),
                       ("所有文件", "*.*")])
        for path in filenames:
            if not path.lower().endswith(SUPPORTED_SUFFIXES):
                logger.warning("跳过不支持的文件：%s", path)
                continue
            database = self.databases.add(path)
            if database.load_error:
                messagebox.showerror(
                    "加载失败",
                    f"{os.path.basename(path)}\n\n{database.load_error}")
        self._reload_db_tree()
        if filenames:
            self.mark_project_dirty()

    def _remove_database(self):
        selection = self.db_tree.selection()
        for iid in selection:
            if iid.startswith("db::"):
                self.databases.remove(iid[4:])
        self._reload_db_tree()
        if selection:
            self.mark_project_dirty()

    def _clear_databases(self):
        self.databases.clear()
        self._reload_db_tree()
        self.mark_project_dirty()

    def _reload_db_tree(self):
        self.db_tree.delete(*self.db_tree.get_children())
        for database in self.databases.databases:
            label = f"{database.name}  ({len(database.messages)})"
            if database.load_error:
                label = f"{database.name}  [加载失败]"
            root = self.db_tree.insert("", END, iid=f"db::{database.path}",
                                       text=label, open=False)
            if database.load_error:
                continue
            messages = self.db_tree.insert(root, END, text="报文", open=False)
            # 只挂前 500 条，几万条报文全挂进 Treeview 会卡住界面
            for info in database.messages[:500]:
                node = self.db_tree.insert(
                    messages, END, text=f"{info.id_text()}  {info.name}")
                for signal in info.signals[:200]:
                    unit = f"  [{signal.unit}]" if signal.unit else ""
                    self.db_tree.insert(node, END, text=f"{signal.name}{unit}")
            if len(database.messages) > 500:
                self.db_tree.insert(messages, END,
                                    text=f"…另有 {len(database.messages) - 500} 条")
            nodes = self.db_tree.insert(root, END, text="节点", open=False)
            for name in database.nodes:
                self.db_tree.insert(nodes, END, text=name)

        count = self.databases.message_count
        self.status_db.configure(
            text=f"{len(self.databases)} 个数据库 / {count} 条报文"
            if count else "无数据库")

    # 给各页面用的查询接口
    def lookup_message(self, frame):
        return self.databases.lookup(frame.can_id, frame.ide)

    def decode_frame(self, frame):
        return self.databases.decode(frame.can_id, frame.data, frame.ide)

    def register_frame_listener(self, callback):
        """页面注册帧回调。连接前注册的，在 connect 时一并挂到设备上。

        回调在**接收线程**里被调用，不要在里面碰 Tk 控件。
        """
        self._frame_listeners.append(callback)
        if self.device is not None:
            self.device.add_listener(callback)

    # ---------- 工程 ----------

    def mark_project_dirty(self):
        """页面改了配置就调一下。加载工程期间不标脏，否则刚打开就显示已修改。"""
        if self._loading_project:
            return
        self.project.mark_dirty()
        self._update_title()

    def _update_title(self):
        self.title(f"{app_meta.DEVICE_NAME} — {self.project.display_name}")

    def _collect_project(self) -> Project:
        project = self.project
        project.databases = [{"path": db.path, "channel": db.chn}
                             for db in self.databases.databases]
        project.device = {"mode": self.conn_mode.get(),
                          "target": self.target_var.get()}
        for key, attr in (("send", "transmit"), ("signal", "watch"),
                          ("graph", "graph"), ("trace", "trace")):
            page = self._pages.get(key)
            if page is not None and hasattr(page, "to_config"):
                setattr(project, attr, page.to_config())
        try:
            geometry = self.winfo_geometry()
        except tk.TclError:
            geometry = ""
        project.layout = {"active_tab": self.notebook.index(self.notebook.select()),
                          "window_geometry": geometry}
        return project

    def _apply_project(self, project: Project):
        self._loading_project = True
        try:
            self.databases.clear()
            for item in project.databases:
                path = item.get("path")
                if not path or not os.path.isfile(path):
                    logger.warning("工程里的数据库不存在，跳过：%s", path)
                    continue
                database = self.databases.add(path, int(item.get("channel", 0)))
                if database.load_error:
                    logger.error("加载失败 %s: %s", path, database.load_error)
            self._reload_db_tree()

            device = project.device or {}
            if device.get("mode"):
                self.conn_mode.set(device["mode"])
                self._on_conn_mode()
            if device.get("target"):
                self.target_var.set(device["target"])

            for key, attr in (("send", "transmit"), ("signal", "watch"),
                              ("graph", "graph"), ("trace", "trace")):
                page = self._pages.get(key)
                data = getattr(project, attr, None)
                if page is not None and hasattr(page, "from_config") and data:
                    try:
                        page.from_config(data)
                    except Exception as error:
                        logger.warning("%s 页恢复配置失败: %s", key, error)

            layout = project.layout or {}
            if layout.get("window_geometry"):
                try:
                    self.geometry(layout["window_geometry"])
                except tk.TclError:
                    pass
            if isinstance(layout.get("active_tab"), int):
                try:
                    self.notebook.select(layout["active_tab"])
                except tk.TclError:
                    pass
        finally:
            self._loading_project = False
        self.project = project
        self.project.dirty = False
        self._update_title()

    def _confirm_discard(self) -> bool:
        """有未保存改动时问一声。返回 False 表示用户取消了操作。"""
        if not self.project.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "未保存的改动", f"工程「{self.project.display_name}」有未保存的改动，"
                            f"要先保存吗？")
        if answer is None:
            return False
        if answer:
            return self._save_project()
        return True

    def _new_project(self):
        if not self._confirm_discard():
            return
        self.databases.clear()
        self._reload_db_tree()
        for key in ("send", "signal", "graph"):
            page = self._pages.get(key)
            if page is not None and hasattr(page, "from_config"):
                page.from_config([])
        self.project = Project()
        self._update_title()

    def _open_project(self, path=None):
        if path is None:
            if not self._confirm_discard():
                return
            path = filedialog.askopenfilename(
                title="打开工程",
                filetypes=[("BusSpy 工程", f"*{PROJECT_SUFFIX}"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            project = Project.load(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("打开失败", f"{path}\n\n{error}")
            return
        self._apply_project(project)

    def _save_project(self) -> bool:
        if not self.project.path:
            return self._save_project_as()
        project = self._collect_project()
        if not project.save():
            messagebox.showerror("保存失败", "详见日志页")
            return False
        self._update_title()
        return True

    def _save_project_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            title="工程另存为", defaultextension=PROJECT_SUFFIX,
            filetypes=[("BusSpy 工程", f"*{PROJECT_SUFFIX}")])
        if not path:
            return False
        project = self._collect_project()
        # 先定路径再序列化，否则相对路径算不对
        project.path = os.path.abspath(path)
        if not project.save(path):
            messagebox.showerror("保存失败", "详见日志页")
            return False
        self._update_title()
        return True

    # ---------- 采集 ----------

    def _on_pause(self):
        self.buffer.set_paused(self.pause_var.get())

    def _clear_all(self):
        self.buffer.clear()
        self._pages["trace"].rebuild()

    def _export_csv(self):
        frames = self.buffer.all_frames()
        if not frames:
            messagebox.showinfo("没有数据", "Trace 缓冲是空的")
            return
        path = filedialog.asksaveasfilename(
            title="导出 Trace", defaultextension=".csv",
            initialdir=paths.trace_dir(),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write("time_s,chn,dir,id,name,dlc,data\n")
                for frame in frames:
                    info = self.lookup_message(frame)
                    handle.write(
                        f"{frame.ts_us / 1e6:.6f},{frame.chn},{frame.direction},"
                        f"{frame.id_text()},{info.name if info else ''},"
                        f"{len(frame.data)},{frame.data_text()}\n")
        except OSError as error:
            messagebox.showerror("导出失败", str(error))
            return
        logger.info("已导出 %d 帧到 %s", len(frames), path)

    # ---------- 刷新 ----------

    def _tick(self):
        try:
            current = self.notebook.index(self.notebook.select())
            # 只刷新当前可见页 + 日志，隐藏页不renders —— 这是不卡的关键之一
            keys = list(self._pages)
            if 0 <= current < len(keys):
                page = self._pages[keys[current]]
                if hasattr(page, "refresh"):
                    page.refresh()
            if keys[current] != "log":
                self._pages["log"].refresh()
            self._refresh_status()
        except Exception as error:
            logger.debug("UI tick 异常: %s", error)
        finally:
            self.after(REFRESH_MS, self._tick)

    def _refresh_status(self):
        if self.device is None:
            return
        stat = self.device.stat
        counters = self.device.counters
        self.status_load.configure(text=f"负载 {stat.bus_load_percent:.1f}%")
        self.status_frames.configure(
            text=f"Rx {counters.rx_frames:,}  Tx {counters.tx_frames:,}")
        ok = stat.err_name == "ACTIVE"
        self.status_err.configure(text=stat.err_name,
                                  bootstyle="success" if ok else "danger")

    # ---------- 主题 / 关闭 ----------

    def _on_theme_change(self):
        name = self.theme_var.get()
        try:
            self.style.theme_use(name)
        except tk.TclError as error:
            logger.warning("切换主题失败: %s", error)
            return
        self._apply_chrome()

    def _apply_chrome(self):
        dark = self.theme_var.get() in DARK_THEMES if hasattr(self, "theme_var") \
            else self.style.theme.name in DARK_THEMES
        apply_titlebar_mode(self, dark)
        for menu in self._menus:
            style_menus(menu, self.style.colors)

    def _about(self):
        # 固件版本来自设备上报，不是本地常量 —— 同一上位机要能连不同版本固件
        messagebox.showinfo(
            "关于",
            f"{app_meta.DEVICE_NAME}\n{app_meta.DESCRIPTION}\n\n"
            f"上位机    {app_meta.host_version_text()}\n"
            f"固件      {app_meta.firmware_version_text(self.device)}\n"
            f"协议      {app_meta.PROTOCOL_NAME} v{app_meta.PROTOCOL_VERSION}\n\n"
            f"{app_meta.COMPANY}")

    def _load_settings(self) -> dict:
        try:
            with open(paths.settings_file(), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return {}

    def _save_settings(self):
        data = dict(self.settings)
        data["theme"] = self.theme_var.get()
        data["conn_mode"] = self.conn_mode.get()
        data["target"] = self.target_var.get()
        if self.project.path:
            data["last_project"] = self.project.path
        try:
            data["window_geometry"] = self.winfo_geometry()
        except tk.TclError:
            pass
        try:
            with open(paths.settings_file(), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except OSError as error:
            logger.debug("保存偏好失败: %s", error)

    def _on_close(self):
        if not self._confirm_discard():
            return
        self._save_settings()
        self.disconnect()
        self.destroy()

    def open_project_on_start(self, path=None):
        """启动时加载工程：命令行给的优先，否则用上次打开的那个。"""
        if path is None:
            path = self.settings.get("last_project")
        if not path or not os.path.isfile(path):
            return
        try:
            self._apply_project(Project.load(path))
        except (OSError, ValueError) as error:
            logger.warning("启动加载工程失败 %s: %s", path, error)
