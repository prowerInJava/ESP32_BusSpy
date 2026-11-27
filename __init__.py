#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ESP32-BusSpyTool 上位机。

分层约定（依赖方向单向）：
    ui -> core -> config/utils
core 不碰界面，ui 只调 core，路径一律走 paths。
"""
from BusSpyTool.config.app_meta import host_version_text

# 版本管理尚未启用，见 config/app_meta.py
__version__ = host_version_text()

__all__ = ["__version__"]
