# ESP32-BusSpyTool

ESP32-S3 + CAN 控制器构建的多总线分析与仿真工具，**仿 CANoe / TSMaster**。

**最终产品目标**：3 路独立 CAN2.0B + 2 路独立 CAN-FD + W5500 以太网；两路 CAN-FD 目标数据段速率最高 8 Mbps（典型负载，待定义验收负载）。**当前开发阶段先做 CAN-FD 1**；另外 4 路 CAN 与 W5500 的软件通道和 GPIO/SPI 资源已按完整产品预留，见 `docs/HARDWARE_PINOUT.md`。总线并发吞吐仍待验证。

> **当前是独立工具**，不依赖任何专用测试框架。

详细设计见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 当前状态

| 部分 | 状态 |
|---|---|
| 上位机（GUI + CLI） | ✅ 可用，Windows / Linux 双平台实测通过 |
| BSTP 协议 / 传输层 / 数据库 | ✅ 可用，自测全绿 |
| 模拟设备 | ✅ 可用，**无硬件也能完整演示** |
| ESP32 固件 | 🧪 RGB 验证程序；通道 ID/驱动接口骨架已建立，MCP2518FD 驱动尚未实现 |

版本号暂不启用，界面与 CLI 一律显示「开发版」。启用后上位机与固件**分开管理**。

## 快速开始（不需要任何硬件）

在可导入 `BusSpyTool` 包的目录下：

```bash
pip install ttkbootstrap cantools pyserial

python -m BusSpyTool.tools.selftest          # core 自测
python -m BusSpyTool.tools.uitest --seconds 8 # UI 冒烟，自动连模拟设备
python -m BusSpyTool.app                      # 开界面，连接方式选「模拟设备」
```

加载你有权限使用的 DBC 看完整效果：

```bash
python -m BusSpyTool.tools.uitest --seconds 10 --tab 1 --autograph 6 \
    --dbc "/path/to/your/sanitized-test.dbc"
```

`--autograph` 会自动往波形页加曲线，`--shot out.png` 可截图。

## 界面

| 页签 | 内容 |
|---|---|
| **Trace** | 实时帧流。**固定模式**按 ID 聚合（行数不随时间增长，高负载不卡）、**滚动模式**看时序细节。行可展开看信号解码 |
| **波形** | 信号曲线，Canvas 自绘。阶梯渲染、各自缩放 / 共用 Y 轴、游标、时间窗口 1s–5min |
| **发送** | 单帧与周期发送。**周期发送下发到固件本地调度**，不是 PC 定时器 |
| **信号** | 信号当前值监控，只解码被监视的报文 |
| **统计** | 设备侧（固件 STAT）与上位机侧计数**分开显示** —— 两边对不上就是链路丢包 |
| **以太网** | 裸 UDP / SOME/IP（界面先行，待固件） |
| **日志** | 程序日志 |

## 命令行（无界面，可在无 X 的机器上跑）

```bash
python -m BusSpyTool.cli ports                       # 列出串口
python -m BusSpyTool.cli monitor --usb COM5          # 实时帧流
python -m BusSpyTool.cli send --usb COM5 --id 123 --fd --data "00 11 22"
python -m BusSpyTool.cli cyc  --usb COM5 --id 123 --period 10
python -m BusSpyTool.cli stat --usb COM5
```

`cli.py` 只 import `core`，**不 import `ui`** —— 无 X 的机器上 import tkinter 会失败。

## 目录

```
BusSpyTool/
├── app.py            GUI 入口（无参开界面，带参转 cli）
├── cli.py            命令行入口
├── paths.py          路径解析唯一出口（含 PyInstaller _MEIPASS）
├── config/           元信息
├── core/             业务核心，不碰界面
│   ├── bstp.py       BSTP v1 协议编解码
│   ├── transport.py  USB CDC / UDP 传输层
│   ├── device.py     设备会话
│   ├── mock.py       模拟设备
│   ├── database.py   DBC / ARXML 运行时加载（cantools）
│   └── tracebuf.py   环形缓冲 + 按 ID 聚合
├── ui/               界面层，只调 core
├── utils/            日志
├── tools/            selftest / uitest
└── docs/DESIGN.md    设计方案
```

依赖方向单向：`ui -> core -> config/utils`。

## 硬件产品架构与当前器件边界

产品系统架构按 3 路独立 CAN2.0B、2 路独立 CAN-FD 和 W5500 规划。当前先交付 CAN-FD 1，不缩减最终产品功能范围。产品 GPIO/SPI 预留方案已列出，并保持当前 CAN-FD 1 引脚不变；PCB 定版前仍须核对 2025-V1.4 板级资料并完成接口/供电及并发吞吐验证。

| 件 | 型号 | 备注 |
|---|---|---|
| 主控 | ESP32-S3 N16R8（当前评估对象） | **Octal PSRAM 占用 GPIO 33–37**；仅 1 个 TWAI 和 2 个通用 SPI 主机，五路全负载能力待验证 |
| CAN-FD | 最终目标 2 路；当前阶段 1 路 | 当前接 MCP2518FD；第二路控制器/收发器预留，双路吞吐待验证 |
| CAN 2.0B | 最终目标 3 路 | 1 路计划用内置 TWAI，另外 2 路需外部控制器；通道 ID 已预留，驱动未实现 |
| 以太网 | W5500 | **专用于被测网络**（接被测 ECU），不接上位机 |
| 显示 | 0.96 英寸 I2C OLED | I2C 预留 GPIO 8/7；可与模式控制 GPIO 扩展器共总线；控制器版本以实物核对 |
| 供电/隔离 | USB-C 5 V；非隔离 | CAN 总线与设备地共地；每路保护、终端和电源预算需产品级设计 |

各通道固定 ID、固件接口与未决硬件风险见 [`docs/HARDWARE_PINOUT.md`](docs/HARDWARE_PINOUT.md)。ID 0–2 保持现有 BSTP v1 含义，新增端点追加 ID；上位机连接计划走 **USB CDC**，ESP32-S3 原生 USB OTG 为 Full-Speed（12 Mbps），五路总线的无损实时上传能力尚未验证。

## 依赖

```
ttkbootstrap>=1.10.1    界面
cantools>=45.0          DBC / ARXML 解析
pyserial>=3.5           USB CDC
Pillow                  图标（ttkbootstrap 依赖）
```

缺 `cantools` 时退化为纯 raw 模式（Trace 只显示 hex），缺 `pyserial` 时只能走 UDP。
