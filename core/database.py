#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :database.py
@Description  :CAN 数据库（DBC / ARXML）运行时加载与信号编解码

这一层是本工具与离线生成型测试框架的**根本区别**：

  这类框架后端使用离线生成的预编译 Python 类，运行时只 import，
  不解析 arxml。

  本工具要像 TSMaster / CANoe 一样**运行时加载任意 DBC / ARXML**，
  所以解析和解码都在运行时路径上。用 cantools 作对象模型与编解码。

无数据库时整个工具仍可用 —— 纯 raw 收发，Trace 只显示 hex。
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from BusSpyTool.utils.logger import logger

try:
    import cantools
    from cantools.database import Database as _CtDatabase
    HAVE_CANTOOLS = True
except ImportError:      # 允许缺依赖时退化成纯 raw 模式
    cantools = None
    _CtDatabase = None
    HAVE_CANTOOLS = False


SUPPORTED_SUFFIXES = (".dbc", ".arxml", ".kcd", ".sym")


@dataclass
class SignalInfo:
    """一条信号的静态定义，供 UI 树与发送面板用。"""
    name: str
    start_bit: int
    length: int
    byte_order: str
    is_signed: bool
    factor: float = 1.0
    offset: float = 0.0
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    comment: str = ""
    choices: Dict[int, str] = field(default_factory=dict)

    @property
    def range_text(self) -> str:
        if self.minimum is None and self.maximum is None:
            return ""
        return f"{self.minimum} ~ {self.maximum}"


@dataclass
class MessageInfo:
    """一条报文的静态定义。"""
    name: str
    frame_id: int
    length: int
    is_extended: bool = False
    is_fd: bool = False
    cycle_ms: Optional[float] = None
    senders: List[str] = field(default_factory=list)
    comment: str = ""
    signals: List[SignalInfo] = field(default_factory=list)

    def id_text(self) -> str:
        return f"{self.frame_id:08X}x" if self.is_extended else f"{self.frame_id:03X}"


class CanDatabase:
    """一个已加载的数据库文件。

    键是 (frame_id, is_extended) —— 同一数值 ID 的标准帧与扩展帧是两条不同报文，
    只用 frame_id 做键会在混用的总线上互相覆盖。
    """

    def __init__(self, path: str, chn: int = 0):
        self.path = path
        self.name = os.path.basename(path)
        self.chn = chn
        self._db = None
        self._messages: Dict[Tuple[int, bool], MessageInfo] = {}
        self._by_name: Dict[str, MessageInfo] = {}
        self.load_error: Optional[str] = None
        self._decode_warned = False

    # ---------- 加载 ----------

    def load(self) -> bool:
        if not HAVE_CANTOOLS:
            self.load_error = "缺少 cantools，无法解析数据库（pip install cantools）"
            logger.error(self.load_error)
            return False
        try:
            self._db = cantools.database.load_file(self.path, strict=False)
        except Exception as error:
            # ARXML 变体很多，cantools 解不了的要如实报错而不是静默空库，
            # 否则用户会以为加载成功但一条报文都认不出来。
            self.load_error = f"{type(error).__name__}: {error}"
            logger.error("加载数据库失败 %s: %s", self.path, self.load_error)
            return False
        self._index()
        logger.info("已加载 %s：%d 条报文", self.name, len(self._messages))
        return True

    def _index(self):
        self._messages.clear()
        self._by_name.clear()
        for msg in getattr(self._db, "messages", []):
            info = MessageInfo(
                name=msg.name,
                frame_id=msg.frame_id,
                length=msg.length,
                is_extended=bool(msg.is_extended_frame),
                is_fd=bool(getattr(msg, "is_fd", False)),
                cycle_ms=getattr(msg, "cycle_time", None),
                senders=list(getattr(msg, "senders", []) or []),
                comment=getattr(msg, "comment", "") or "",
                signals=[self._signal_info(s) for s in getattr(msg, "signals", [])],
            )
            self._messages[(info.frame_id, info.is_extended)] = info
            self._by_name[info.name] = info

    @staticmethod
    def _signal_info(sig) -> SignalInfo:
        choices = {}
        raw_choices = getattr(sig, "choices", None) or {}
        for key, value in raw_choices.items():
            try:
                choices[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        return SignalInfo(
            name=sig.name,
            start_bit=sig.start,
            length=sig.length,
            byte_order=getattr(sig, "byte_order", "little_endian"),
            is_signed=bool(getattr(sig, "is_signed", False)),
            factor=getattr(sig, "scale", 1.0) or 1.0,
            offset=getattr(sig, "offset", 0.0) or 0.0,
            unit=getattr(sig, "unit", "") or "",
            minimum=getattr(sig, "minimum", None),
            maximum=getattr(sig, "maximum", None),
            comment=getattr(sig, "comment", "") or "",
            choices=choices,
        )

    # ---------- 查询 ----------

    @property
    def messages(self) -> List[MessageInfo]:
        return list(self._messages.values())

    @property
    def nodes(self) -> List[str]:
        names = set()
        for info in self._messages.values():
            names.update(info.senders)
        return sorted(names)

    def message_by_id(self, frame_id: int, is_extended: bool = False) -> Optional[MessageInfo]:
        return self._messages.get((frame_id, is_extended))

    def message_by_name(self, name: str) -> Optional[MessageInfo]:
        return self._by_name.get(name)

    # ---------- 编解码 ----------

    def decode(self, frame_id: int, data: bytes, is_extended: bool = False) -> Optional[dict]:
        """解码一帧为 {信号名: 物理值}。认不出或数据不足时返回 None。"""
        if self._db is None:
            return None
        try:
            return self._db.decode_message(
                frame_id, data, decode_choices=False,
                allow_truncated=True, force_extended_id=is_extended)
        except Exception as error:
            # Trace 是热路径，解不开就当 raw 显示，不能每帧刷日志（一秒几千条）。
            # 但**第一次**失败必须记一笔：参数名写错这类问题会让所有信号都解不出来，
            # 若完全静默就只能看到「波形图是空的」而毫无线索。
            if not self._decode_warned:
                self._decode_warned = True
                logger.warning(
                    "解码失败 %s id=0x%X（后续同类不再记录）: %s: %s",
                    self.name, frame_id, type(error).__name__, error)
            return None

    def encode(self, name: str, values: dict) -> Optional[bytes]:
        """按信号值编码一帧。缺失信号由 cantools 用默认/初值补齐。"""
        if self._db is None:
            return None
        try:
            return self._db.encode_message(name, values, strict=False, padding=True)
        except Exception as error:
            logger.warning("编码 %s 失败: %s", name, error)
            return None


class DatabaseManager:
    """多数据库管理，仿 CANoe 的「数据库」节点 / TSMaster 的数据库列表。

    一条总线可挂多个 DBC（区域架构常见）。解码时按加载顺序找第一个认得的，
    与 CANoe 的行为一致。
    """

    def __init__(self):
        self._dbs: List[CanDatabase] = []

    def __len__(self):
        return len(self._dbs)

    @property
    def databases(self) -> List[CanDatabase]:
        return list(self._dbs)

    @property
    def message_count(self) -> int:
        return sum(len(db.messages) for db in self._dbs)

    def add(self, path: str, chn: int = 0) -> CanDatabase:
        db = CanDatabase(path, chn)
        db.load()
        self._dbs.append(db)
        return db

    def remove(self, path: str):
        self._dbs = [d for d in self._dbs if d.path != path]

    def clear(self):
        self._dbs.clear()

    def lookup(self, frame_id: int, is_extended: bool = False) -> Optional[MessageInfo]:
        for db in self._dbs:
            info = db.message_by_id(frame_id, is_extended)
            if info is not None:
                return info
        return None

    def decode(self, frame_id: int, data: bytes, is_extended: bool = False):
        """返回 (MessageInfo, {信号名: 值})，认不出返回 (None, None)。"""
        for db in self._dbs:
            info = db.message_by_id(frame_id, is_extended)
            if info is None:
                continue
            return info, db.decode(frame_id, data, is_extended)
        return None, None

    def all_messages(self) -> List[MessageInfo]:
        out = []
        for db in self._dbs:
            out.extend(db.messages)
        return out
