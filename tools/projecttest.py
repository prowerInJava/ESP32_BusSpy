#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""工程文件端到端验证：起界面 -> 配置 -> 存盘 -> 新建清空 -> 读回 -> 比对。

这个必须起真窗口，因为 to_config/from_config 都挂在页面上。
跑法（platform_auto_test_tools 目录下）：
    python -m BusSpyTool.tools.projecttest <dbc路径>
"""
import os
import sys
import tempfile


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("用法: python -m BusSpyTool.tools.projecttest <dbc路径>")
        return 2
    dbc = argv[0]
    if not os.path.isfile(dbc):
        print(f"找不到 {dbc}")
        return 2

    from BusSpyTool.ui import enable_per_monitor_dpi
    enable_per_monitor_dpi()
    from BusSpyTool.core.project import Project
    from BusSpyTool.ui.main_window import MainWindow
    from BusSpyTool.ui.send_page import SendEntry

    failures = []

    def check(name, cond, detail=""):
        print(f"  [{'ok' if cond else 'FAIL'}]   {name}" +
              (f"  {detail}" if not cond and detail else ""))
        if not cond:
            failures.append(name)

    window = MainWindow()
    window.withdraw()          # 不需要真显示，只要控件树在
    try:
        # ---- 配置 ----
        database = window.databases.add(dbc)
        check("数据库加载", not database.load_error, database.load_error or "")
        window._reload_db_tree()
        messages = window.databases.all_messages()
        check("有报文", len(messages) > 0, str(len(messages)))

        send = window._pages["send"]
        entry = SendEntry.from_config(
            {"name": "写 VIN", "chn": 0, "id": "0x7E0", "fd": True,
             "brs": True, "data": "02 10 03", "period_ms": 0})
        iid = send.tree.insert("", "end", values=send._values(entry))
        send.entries[iid] = entry
        check("发送项已加入", len(send.entries) == 1)

        picks = []
        for info in messages:
            for signal in info.signals:
                if signal.length > 1 and not signal.choices:
                    picks.append((info, signal))
                    break
            if len(picks) >= 3:
                break
        window._pages["graph"]._add_series(picks)
        window._pages["signal"]._add_items(picks[:2])
        check("波形曲线", len(window._pages["graph"].series) == len(picks),
              str(len(window._pages["graph"].series)))
        check("监控信号", len(window._pages["signal"].items) == 2)

        window._pages["trace"].mode.set("scroll")
        window._pages["trace"].filter_var.set("123")

        # ---- 存盘 ----
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "e2e.bsp")
            project = window._collect_project()
            project.path = os.path.abspath(path)
            check("保存", project.save(path) is True)
            check("文件存在", os.path.isfile(path))

            saved_send = len(project.transmit)
            saved_graph = len(project.graph)
            saved_watch = len(project.watch)
            saved_trace = dict(project.trace)
            print(f"    存了 {saved_send} 发送项 / {saved_graph} 曲线 / "
                  f"{saved_watch} 监控 / trace={saved_trace}")

            # ---- 新建清空 ----
            window.project.dirty = False      # 跳过确认框
            window._new_project()
            check("新建后数据库清空", len(window.databases) == 0)
            check("新建后发送列表清空", len(send.entries) == 0)
            check("新建后曲线清空", len(window._pages["graph"].series) == 0)

            # ---- 读回 ----
            window._apply_project(Project.load(path))
            check("读回数据库", len(window.databases) == 1,
                  str(len(window.databases)))
            check("读回发送项", len(send.entries) == saved_send,
                  f"{len(send.entries)} vs {saved_send}")
            check("读回发送项名称",
                  any(e.name == "写 VIN" for e in send.entries.values()),
                  str([e.name for e in send.entries.values()]))
            check("读回曲线", len(window._pages["graph"].series) == saved_graph,
                  f"{len(window._pages['graph'].series)} vs {saved_graph}")
            check("读回监控", len(window._pages["signal"].items) == saved_watch,
                  f"{len(window._pages['signal'].items)} vs {saved_watch}")
            check("读回 trace 模式",
                  window._pages["trace"].mode.get() == saved_trace.get("mode"),
                  window._pages["trace"].mode.get())
            check("读回 trace 过滤",
                  window._pages["trace"].filter_var.get() == "123",
                  window._pages["trace"].filter_var.get())
            check("读回后不脏", window.project.dirty is False)

            # ---- 脏标记 ----
            window.mark_project_dirty()
            check("改动后标脏", window.project.dirty is True)
            check("标题带星号", window.project.display_name.endswith("*"),
                  window.project.display_name)
    finally:
        try:
            window.project.dirty = False
            window.destroy()
        except Exception:
            pass

    print("=" * 56)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("工程文件端到端验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
