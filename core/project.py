#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :project.py
@Description  :工程文件 —— 仿 CANoe 的 Configuration，打开即用

把「总线网络 + 数据库 + 常用收发项 + 监控/波形」存成一个文件，
下次打开直接干活，不用重配。

设计原则：**工具只提供机制，业务含义由用户配置表达。**
「写 VIN」「刷 CCP」「唤醒序列」「故障注入」这些都不是内置功能，
它们就是用户在发送列表里配的几条报文加个名字而已。
判据：只对某个项目 / 某个 ECU 有意义的东西，就该是配置而不是代码。

与 settings.json 的分工，不要混：
    settings.json   主题、窗口几何、上次用的串口 —— 程序偏好，跟这台电脑走
    *.bsp           数据库、发送列表、监控/波形 —— 工作内容，跟项目走，可分发

路径一律存**相对于工程文件所在目录**的相对路径，否则把工程发给同事全是断链；
只有目标不在工程目录树下（比如跨盘符）时才退化为绝对路径。
"""
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from BusSpyTool.utils.logger import logger

PROJECT_SUFFIX = ".bsp"
PROJECT_VERSION = 1


@dataclass
class Project:
    """一个工程。字段与 docs/DESIGN.md §5.4 的 JSON 结构一一对应。"""

    name: str = "未命名工程"
    databases: List[Dict[str, Any]] = field(default_factory=list)
    device: Dict[str, Any] = field(default_factory=dict)
    transmit: List[Dict[str, Any]] = field(default_factory=list)
    watch: List[Dict[str, Any]] = field(default_factory=list)
    graph: List[Dict[str, Any]] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)
    layout: Dict[str, Any] = field(default_factory=dict)

    # 运行态，不写进文件
    path: Optional[str] = None
    dirty: bool = False

    # ---------- 标题 ----------

    @property
    def display_name(self) -> str:
        base = os.path.basename(self.path) if self.path else self.name
        return f"{base}{' *' if self.dirty else ''}"

    def mark_dirty(self):
        self.dirty = True

    # ---------- 路径相对化 ----------

    def _base_dir(self) -> Optional[str]:
        return os.path.dirname(os.path.abspath(self.path)) if self.path else None

    def to_relative(self, target: str) -> str:
        """存盘时用。不在工程目录树下（含跨盘符）就保持绝对路径。"""
        base = self._base_dir()
        if not base or not target:
            return target
        try:
            relative = os.path.relpath(target, base)
        except ValueError:
            # Windows 跨盘符，relpath 直接抛错
            return target
        if relative.startswith(".."):
            return target
        return relative.replace("\\", "/")

    def to_absolute(self, stored: str) -> str:
        """读盘时用。"""
        base = self._base_dir()
        if not base or not stored or os.path.isabs(stored):
            return stored
        return os.path.normpath(os.path.join(base, stored))

    # ---------- 读写 ----------

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "version": PROJECT_VERSION,
            "name": self.name,
            "databases": [
                {**item, "path": self.to_relative(item.get("path", ""))}
                for item in self.databases
            ],
            "device": self.device,
            "transmit": self.transmit,
            "watch": self.watch,
            "graph": self.graph,
            "trace": self.trace,
            "layout": self.layout,
        }
        return data

    def save(self, path: Optional[str] = None) -> bool:
        if path:
            self.path = os.path.abspath(path)
        if not self.path:
            raise ValueError("工程还没有路径，请用「另存为」")
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
        except OSError as error:
            logger.error("保存工程失败 %s: %s", self.path, error)
            return False
        self.dirty = False
        logger.info("工程已保存 %s", self.path)
        return True

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("工程文件格式不对：顶层不是对象")

        version = data.get("version", 0)
        if version > PROJECT_VERSION:
            # 不拒绝打开 —— 多出来的字段忽略即可，但要让用户知道
            logger.warning("工程版本 %s 高于本程序支持的 %s，部分配置可能被忽略",
                           version, PROJECT_VERSION)

        project = cls(
            name=data.get("name") or os.path.splitext(os.path.basename(path))[0],
            databases=list(data.get("databases") or []),
            device=dict(data.get("device") or {}),
            transmit=list(data.get("transmit") or []),
            watch=list(data.get("watch") or []),
            graph=list(data.get("graph") or []),
            trace=dict(data.get("trace") or {}),
            layout=dict(data.get("layout") or {}),
        )
        project.path = os.path.abspath(path)
        # 路径转回绝对，后续各层只跟绝对路径打交道
        for item in project.databases:
            item["path"] = project.to_absolute(item.get("path", ""))
        project.dirty = False
        logger.info("已打开工程 %s（%d 个数据库 / %d 条发送项）",
                    project.path, len(project.databases), len(project.transmit))
        return project
