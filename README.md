# ESP32-BusSpyTool

ESP32-S3 + MCP2518FD 自制的多总线分析与仿真工具，**仿 CANoe / TSMaster**：
单通道 CAN-FD + CAN 2.0 预留通道 + 以太网侧信号。

> **当前是独立工具**，不依赖任何专用测试框架。

详细设计见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 当前状态

| 部分 | 状态 |
|---|---|
| 上位机（GUI + CLI） | ✅ 可用，Windows / Linux 双平台实测通过 |
| BSTP 协议 / 传输层 / 数据库 | ✅ 可用，自测全绿 |
| 模拟设备 | ✅ 可用，**无硬件也能完整演示** |
| ESP32 固件 | 🧪 RGB 灯常亮验证程序已开始 |

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

## 硬件（主固件尚未开始）

| 件 | 型号 | 备注 |
|---|---|---|
| 主控 | ESP32-S3 N16R8 | **Octal PSRAM 占用 GPIO 33–37**，引脚分配要避开 |
| CAN-FD | MCP2518FD + 收发器 | **晶振必须 40 MHz**，20 MHz 算不出 8 Mbps |
| CAN 2.0 | SN65HVD230 | 接内置 TWAI，预留通道 |
| 以太网 | W5500 | **专用于被测网络**（接被测 ECU），不接上位机 |

上位机连接计划走 **USB CDC**。ESP32-S3 有原生 USB Serial/JTAG 控制器，可枚举为虚拟串口并支持 esptool 烧录；它与可配置的 USB-OTG 功能不是同一概念。

## 依赖

```
ttkbootstrap>=1.10.1    界面
cantools>=45.0          DBC / ARXML 解析
pyserial>=3.5           USB CDC
Pillow                  图标（ttkbootstrap 依赖）
```

缺 `cantools` 时退化为纯 raw 模式（Trace 只显示 hex），缺 `pyserial` 时只能走 UDP。
