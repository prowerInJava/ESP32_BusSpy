# ESP32-S3、MCP2518FD Pro 与 OLED 硬件针脚说明

## 当前单路 CAN-FD 台架接线参考

这张图只说明现有 ESP32-S3 开发板、单块 MCP2518FD Pro 模块和 OLED 的台架接法，**不是最终产品原理图或 PCB 布线图**。MCP 的 GPIO 9–13 只作为当前模块接线记录；产品 GPIO 分配须对照用户指定的 ESP32-S3 2025-V1.4 图纸核实后再冻结，不沿用旧引脚图推导扩展通道。

![ESP32-S3、MCP2518FD Pro 与 OLED 三板接线图](./images/ESP32-S3-MCP2518FD-OLED-接线图.svg)

## ESP32-S3 到 MCP2518FD Pro

| ESP32-S3 针脚 | MCP2518FD Pro 针脚 | 用途 |
|---|---|---|
| GPIO 12 | SCK | SPI 时钟，ESP32 输出 |
| GPIO 11 | SDI | SPI MOSI，ESP32 向 MCP 发送 |
| GPIO 13 | SDO | SPI MISO，MCP 向 ESP32 返回 |
| GPIO 10 | CS | SPI 片选，低电平有效 |
| GPIO 9 | INT | MCP 中断输出，通知 ESP32 读取接收 FIFO/状态 |
| 3V3 | 3V3 | MCP 模块逻辑 I/O 电源；将模块 P3 选择到 3V3 |
| 5V | 5V | MCP 模块的 5V 供电输入，供板上 CAN 收发器电源部分使用 |
| GND | GND | 共地 |

ESP32-S3 的 SPI 信号使用 3.3V 逻辑。不要把模块 P3 设为 5V 逻辑。

开发板上的两个 `3V3` 针脚属于同一条 3.3V 电源轨，可以分别给 MCP 的 `3V3` 和 OLED 的 `VCC` 供电；也可以从一个 `3V3` 针脚分接。所有标有 `GND` 的 ESP32 针脚共地，接任意一个标有 `GND` 的针脚即可；不要把“共地”理解为 GPIO 或其他针脚也能接地。

## 分阶段产品目标与软件通道预留

![五路 CAN 与 W5500 产品架构图](./images/ESP32-S3-5-CAN-product-architecture.svg)

| 项目 | 用户确认的目标 |
|---|---|
| CAN 物理口 | 3 路独立 CAN2.0B + 2 路独立 CAN-FD，共 5 路 |
| CAN-FD 数据段速率 | 两路目标最高 8 Mbps；典型负载，具体利用率/零丢帧验收值未定 |
| 以太网 | 保留 W5500 |
| 供电/隔离 | USB-C 5 V；非隔离，CAN 地与设备地共地 |

当前软件/固件阶段先按 **CAN-FD 1** 建立通道接口。其余 4 路 CAN 和 W5500 保留固定软件 ID 与驱动接入点，不代表对应硬件驱动已经实现或可以使用。

| BSTP 通道 ID | 端点 | 阶段 | 预期硬件路径 |
|---:|---|---|---|
| 0 | CAN-FD 1 | 当前阶段 | MCP2518FD 控制器 + CAN-FD 收发器 |
| 1 | CAN2.0B 1 | 预留 | ESP32-S3 TWAI + 经典 CAN 收发器 |
| 2 | Ethernet | 预留 | W5500；独立网络接口，不是 CAN 控制器 |
| 3 | CAN-FD 2 | 预留 | 独立 CAN-FD 控制器 + 收发器 |
| 4 | CAN2.0B 2 | 预留 | 独立外部经典 CAN 控制器 + 收发器 |
| 5 | CAN2.0B 3 | 预留 | 独立外部经典 CAN 控制器 + 收发器 |

ID 0–2 保留现有 BSTP v1 含义，新增端点只追加 ID，不重排或复用旧 ID。上位机定义见 `core/bstp.py:Chn`；固件的 CAN 驱动与 Ethernet 数据报接口见 `demo/fireware/main/busspy_interfaces.h`。CAN 控制器经统一 CAN 驱动接口接入；W5500 使用独立 Ethernet 接口，避免把网络包伪装成 CAN 通道。

ESP32-S3 只有 **1 个 TWAI 控制器和 2 个通用 SPI 主机**。完整目标中其余控制器与 W5500 的 SPI 分组、片选、中断和总线时隙必须在 2025-V1.4 板级资料核对后共同规划；当前不冻结 GPIO 或 SPI 分组。两路 CAN-FD 目标 8 Mbps，但五路同时负载、USB 上传与 W5500 吞吐均未验证，不能据此承诺满载零丢帧。

**当前固件边界**：`demo/fireware` 仍是 RGB 验证程序；现在加入的是稳定通道目录和驱动接口骨架，CAN-FD1 的 MCP2518FD 驱动、BSTP 固件传输和实际收发尚未完成。新增 CAN 控制器或 W5500 时应实现既有接口并绑定相应 ID，而不是重做上位机通道模型。

**产品板要求**：每路 CAN 独立连接器与收发器；每路单独设计可配置的 120 Ω 终端、ESD/浪涌保护和地参考。当前用户选定非隔离，所有 CAN 端与 USB/设备地共地，必须做共模电压、地环流和故障能量评估。USB-C 5 V 供电需按 ESP32-S3、5 路收发器、W5500 的峰值电流和热耗散重新做电源预算；不能直接沿用开发板稳压器假设。

## ESP32-S3 到 OLED

| ESP32-S3 针脚 | OLED 针脚 | 用途 |
|---|---|---|
| GPIO 8 | SCL | I2C 时钟 |
| GPIO 7 | SDA | I2C 数据 |
| 3V3 | VCC | 屏幕供电；模块规格未确认前不要接 5V |
| GND | GND | 共地 |

当前使用的是新款 OLED：针脚顺序为 `GND`、`VCC`、`SCL`、`SDA`；背面丝印给出 `0x78` / `0x7A` 两个地址选项，按常见 8 位写地址表示法对应 7 位地址 `0x3C` / `0x3D`。焊桥地址需扫描确认；控制器按新款资料优先评估 SSD1315，详见 [OLED 接线说明](./OLED接线说明.md)。

## MCP2518FD Pro 排针功能

以下名称按模块照片上的丝印记录；模块方向不同会改变它们在照片中的上下/左右位置，接线时认针脚文字，不要只按“左排/右排”判断。

| MCP 模块丝印 | 功能 | 基础接线建议 |
|---|---|---|
| STBY | 板载 CAN 收发器待机控制 | **必须定义电平**；产品上用默认电阻/跳线保证上电处于所需模式，可选 MCU 控制 |
| NS | 板载收发器的 NSIL（Normal/Silent）控制；照片上芯片区域标有 `NSIL/VIO` | **必须定义电平**；不是 CANH/CANL。产品上按收发器版本设正常/静默默认态，可选 MCU 控制 |
| CS | MCP2518FD SPI 片选，低有效 | 接 ESP GPIO 10 |
| SCK | SPI 时钟输入 | 接 ESP GPIO 12 |
| SDO | SPI 数据输出（MISO） | 接 ESP GPIO 13 |
| SDI | SPI 数据输入（MOSI） | 接 ESP GPIO 11 |
| 3V3 | 逻辑 I/O 电源 | 接 ESP 3V3；P3 选择 3V3 |
| GND（两处） | 地 | 与 ESP 共地 |
| CLKO | MCP 时钟输出 | 基础 SPI 通信不需要，可不接 |
| INT | MCP 主中断输出 | 推荐接 ESP GPIO 9；只有采用轮询驱动时才可不接，产品固件通常应优先使用中断 |
| INT0、INT1 | MCP 可配置辅助 GPIO/中断功能（以模块原理图和芯片配置为准） | 不用相关功能时可不接；产品 PCB 可留测试焊盘，固件勿配置成未定义的输出状态 |
| NC（两处） | 未连接/预留 | 保持不接，不要在产品 PCB 上擅自接电源或信号 |
| 5V | 模块 5V 供电输入 | 接 ESP 5V |

模块上的 `STBY`、`NS`/`NSIL` 模式选择与板载收发器版本、焊桥设置有关。不要因为接口排针上有这些脚就直接接到 ESP GPIO；先按板上选择位/模块资料设为正常收发模式。常见 ATA6560 系列的正常模式逻辑为 STBY 低、NSIL 高，但此板丝印还标出收发器变体，实际以模块配置为准。

`CLKO` 是 MCP 的时钟输出，不是正常 SPI 通信所需的时钟输入；不使用该输出时可不接。成熟产品可以把它引到测试点，便于测量时钟，但只有确认有诊断/同步用途后才需要接 MCU。这里的“可不接”表示该功能未使用时允许保持未连接，不代表所有排针都可以悬空：`STBY` 和 `NS`/`NSIL` 仍须有确定的默认状态。

## CAN 总线端

照片上可见 `CH`、`CL` 测试点，分别标示 CANH、CANL。DB9 的具体针脚映射不能仅凭外观确认；若要确认本模块 DB9 的 CANH/CANL 针脚，先断电，再用万用表通断档从 CH/CL 测到 DB9 针脚。不要把常见 DB9 标准针脚号直接当成本模块已验证的映射。

## 实物参考照片

这些照片保留原始内容，用于核对板上丝印和模块版本；实际接线仍以手上板子的标记为准。

### MCP2518FD Pro

![MCP2518FD Pro 实物照片](./images/hardware-reference/MCP2518FD-Pro-module-photo.jpg)

### OLED 模块背面

![OLED 模块背面丝印](./images/hardware-reference/OLED-JMD0.96D-I-back.png)

## 接线与上电顺序

1. 拔掉 ESP32-S3 USB 电源。
2. 先接 MCP 的 SPI、INT、3V3、5V、GND，再接 OLED 的 SCL、SDA、VCC、GND。
3. 确认 MCP 模块 P3 选 3V3，OLED VCC 接 ESP 3V3，所有 GND 共地，且没有短接。
4. 再接 USB 上电；先做 I2C 扫描与 MCP SPI 识别测试，不要在未确认 CAN 收发器模式和总线接线前接入车辆/带电 CAN 网络。
