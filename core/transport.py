#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :transport.py
@Description  :BSTP 传输层抽象 —— USB CDC / UDP 两条路

为什么要抽象：接上位机有三条物理路径，各有适用场景，而 BSTP 之上
的逻辑（帧、周期槽、状态）完全一样。

    USB CDC-ACM   ESP32-S3 原生 USB-OTG 2.0 **Full-Speed（12 Mbps）**，
                  CDC 实测有效 ~500-900 KB/s。免配 IP、低延迟、USB 层
                  自带重传、同时供电。**默认首选**，且不占用 W5500。
    Wi-Fi (UDP)   无线调试 / 设备装在机柜里不便接线时用。抖动大但不影响
                  时序判定（时间戳是固件侧硬件 TBC 打的）。
    以太网 (UDP)  W5500。**但 W5500 应专用于被测以太网**（接 ADCU 收发
                  SOME/IP / 裸 UDP 信号），一般不用它接上位机。

关键差异：UDP 是数据报，天然有包边界；USB CDC 是**字节流**，没有边界。
好在 BSTP 头自带 magic(4B) + payload_len(2B)，可以直接做流式重同步，
不需要额外的 SLIP/COBS 转义开销 —— 见 SerialTransport._extract。
"""
import abc
import socket
import struct
from typing import List, Optional, Tuple

from BusSpyTool.core import bstp
from BusSpyTool.core.bstp import HDR_FMT, HDR_SIZE, MAGIC, Packet
from BusSpyTool.utils.logger import logger

try:
    import serial                      # pyserial
    from serial.tools import list_ports
    HAVE_SERIAL = True
except ImportError:
    serial = None
    list_ports = None
    HAVE_SERIAL = False

_MAGIC_LE = struct.pack("<I", MAGIC)
MAX_PAYLOAD = 2048


class Transport(abc.ABC):
    """BSTP 传输通道。实现方只管收发整包，不懂 BSTP 语义。"""

    name = "base"

    @abc.abstractmethod
    def open(self) -> bool:
        ...

    @abc.abstractmethod
    def close(self):
        ...

    @abc.abstractmethod
    def send(self, packet: Packet) -> bool:
        ...

    @abc.abstractmethod
    def recv(self, timeout: float = 0.2) -> List[Packet]:
        """取出当前可读的所有完整包。超时返回空列表，不抛异常。"""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        ...


class UdpTransport(Transport):
    """Wi-Fi 或以太网。一个 UDP 包一个 BSTP 包。"""

    name = "udp"

    def __init__(self, host: str, port: int = 8000, local_port: Optional[int] = None):
        self.host = host
        self.port = port
        # 沿用「设备收 port、上位机收 port+1」的约定
        self.local_port = local_port if local_port is not None else port + 1
        self._sock: Optional[socket.socket] = None
        self.bad_packets = 0

    @property
    def description(self) -> str:
        return f"UDP {self.host}:{self.port}"

    def open(self) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # 只绑端口不绑地址：设备可能从 Wi-Fi 或有线口任一侧回包
            sock.bind(("", self.local_port))
            sock.settimeout(0.2)
        except OSError as error:
            logger.error("UDP 绑定本地端口 %d 失败: %s", self.local_port, error)
            return False
        self._sock = sock
        return True

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def send(self, packet: Packet) -> bool:
        if not self._sock:
            return False
        try:
            self._sock.sendto(packet.encode(), (self.host, self.port))
            return True
        except OSError as error:
            logger.warning("UDP 发送失败: %s", error)
            return False

    def recv(self, timeout: float = 0.2) -> List[Packet]:
        if not self._sock:
            return []
        self._sock.settimeout(timeout)
        out: List[Packet] = []
        while True:
            try:
                raw, _addr = self._sock.recvfrom(MAX_PAYLOAD)
            except socket.timeout:
                break
            except OSError:
                break
            try:
                out.append(Packet.decode(raw))
            except bstp.BstpError:
                # 整包丢弃并计数，不做部分解析
                self.bad_packets += 1
            if len(out) >= 64:        # 一轮别收太多，让 UI 有机会刷新
                break
        return out


class SerialTransport(Transport):
    """USB CDC-ACM。字节流，靠 magic + payload_len 做重同步。

    Windows 下设备是 COM 口，Linux 下是 /dev/ttyACM*，两边都原生支持，
    不需要装驱动（这是选 CDC-ACM 而不是 USB-ECM/RNDIS 的主要原因 ——
    ECM 在 Windows 上要驱动，RNDIS 在 Linux 上有坑，跨平台一致性差）。
    """

    name = "usb"

    def __init__(self, port: str, baudrate: int = 921600):
        self.port = port
        # CDC-ACM 的波特率是摆设（USB 不是真串口），但 pyserial 要求给值
        self.baudrate = baudrate
        self._ser = None
        self._buf = bytearray()
        self.bad_packets = 0
        self.resync_bytes = 0

    @property
    def description(self) -> str:
        return f"USB {self.port}"

    @staticmethod
    def list_candidates() -> List[Tuple[str, str]]:
        """列出可能是 ESP32-S3 的串口，返回 [(device, description)]。

        ESP32-S3 原生 USB 的 VID 是 Espressif 的 0x303A，排在最前。
        也把 CH340/CP210x 列出来 —— DevKit 上那颗 UART 桥也能跑 BSTP。
        """
        if not HAVE_SERIAL:
            return []
        out = []
        for info in list_ports.comports():
            vid = getattr(info, "vid", None)
            text = f"{info.device}  {info.description or ''}".strip()
            if vid == 0x303A:
                out.insert(0, (info.device, text + "  [ESP32 native USB]"))
            else:
                out.append((info.device, text))
        return out

    def open(self) -> bool:
        if not HAVE_SERIAL:
            logger.error("缺少 pyserial，无法走 USB（pip install pyserial）")
            return False
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=0.05,
                                      write_timeout=1.0)
        except Exception as error:
            logger.error("打开串口 %s 失败: %s", self.port, error)
            return False
        self._buf.clear()
        return True

    def close(self):
        if self._ser:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def send(self, packet: Packet) -> bool:
        if not self._ser:
            return False
        try:
            self._ser.write(packet.encode())
            return True
        except Exception as error:
            # write_timeout 必须设，否则对端不读时这里会永久阻塞住 UI
            logger.warning("串口发送失败: %s", error)
            return False

    def recv(self, timeout: float = 0.2) -> List[Packet]:
        if not self._ser:
            return []
        try:
            self._ser.timeout = timeout
            chunk = self._ser.read(4096)
        except Exception as error:
            logger.warning("串口读取失败: %s", error)
            return []
        if chunk:
            self._buf.extend(chunk)
        return self._extract()

    def _extract(self) -> List[Packet]:
        """从字节流里切出完整的 BSTP 包。

        流式重同步：找 magic -> 读 payload_len -> 够长就取包。
        magic 之前的垃圾字节丢弃并计入 resync_bytes（上电噪声、固件
        printf 混进 CDC 都会产生，不该当成错误包）。
        """
        out: List[Packet] = []
        while True:
            index = self._buf.find(_MAGIC_LE)
            if index < 0:
                # 没找到 magic：保留末尾 3 字节，可能是被切断的 magic
                if len(self._buf) > 3:
                    self.resync_bytes += len(self._buf) - 3
                    del self._buf[:-3]
                break
            if index > 0:
                self.resync_bytes += index
                del self._buf[:index]
            if len(self._buf) < HDR_SIZE:
                break
            plen = struct.unpack_from(HDR_FMT, self._buf, 0)[4]
            if plen > MAX_PAYLOAD:
                # 明显不合理的长度：这个 magic 是假的，跳过 4 字节继续找
                self.bad_packets += 1
                del self._buf[:4]
                continue
            total = HDR_SIZE + plen
            if len(self._buf) < total:
                break
            raw = bytes(self._buf[:total])
            del self._buf[:total]
            try:
                out.append(Packet.decode(raw))
            except bstp.BstpError:
                self.bad_packets += 1
        return out
