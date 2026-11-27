#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File         :logger.py
@Description  :全局 logger。文件落在 paths.log_dir()，按大小滚动。

禁止用 print 做日志（仓库口径）。--windowed 打包后 stdout 不存在，
print 会在 Windows 上直接抛 OSError，所以这里也不挂 StreamHandler
到 sys.stdout —— 只在有真实 stdout 时才加。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from BusSpyTool import paths

_LOG_NAME = "BusSpyTool"
_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def _build_logger():
    log = logging.getLogger(_LOG_NAME)
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)
    log.propagate = False

    try:
        directory = paths.log_dir()
        os.makedirs(directory, exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(directory, "busspy.log"),
            maxBytes=4 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler.setLevel(logging.DEBUG)
        log.addHandler(handler)
    except OSError:
        # 日志目录建不起来不该让程序起不来
        pass

    # --windowed 下 sys.stderr 是 None
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(_FORMAT))
        console.setLevel(logging.INFO)
        log.addHandler(console)
    return log


logger = _build_logger()
