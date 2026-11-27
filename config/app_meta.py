#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :app_meta.py
@Description  :程序元信息

**版本号暂不启用** —— 等成品做到一定规模再开始管理。届时上位机与固件
分开管理，互不绑定：

    HOST_VERSION       上位机（本程序）的版本，由构建脚本写入
    FIRMWARE_VERSION   ESP32 固件的版本，由设备在 HELLO_ACK 里上报，
                       **不写死在这里** —— 同一个上位机要能连不同版本的固件

在那之前，界面与 CLI 一律显示「开发版」，不编造版本号。
"""

APP_NAME = "BusSpyTool"
DEVICE_NAME = "ESP32-BusSpyTool"
COMPANY = "Qianli"
AUTHOR = "Qianli Platform Test"
DESCRIPTION = "单通道 CAN-FD / CAN 2.0 / 以太网 总线分析与仿真工具"

# 版本管理启用前的占位。不要在别处硬编码版本字符串。
HOST_VERSION = None
VERSION_LABEL = "开发版"

PROTOCOL_NAME = "BSTP"
PROTOCOL_VERSION = 1


def host_version_text() -> str:
    """上位机版本的显示文本。未启用版本管理时返回「开发版」。"""
    return HOST_VERSION or VERSION_LABEL


def firmware_version_text(device) -> str:
    """固件版本的显示文本。来源是设备上报，不是本地常量。"""
    version = getattr(device, "firmware_version", None) if device else None
    return version or "未知"
