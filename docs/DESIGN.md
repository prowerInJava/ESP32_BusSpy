# ESP32-BusSpyTool 设计方案

> **ESP32-BusSpyTool** —— 用 ESP32-S3 N16R8 + CAN 控制器构建的多总线分析与仿真工具：
> 产品架构为 3 路经典 CAN + 2 路 CAN-FD + W5500；按实施阶段先交付 CAN-FD 1，其余端点从现在起纳入统一的软件接口与资源规划。
>
> **定位：一个独立的仿 CANoe / TSMaster 工具，当前不依赖外部测试框架。**
>
> 另一种树莓派 + SocketCAN 方案尚未实现；本文描述 MCU 固件路线，两者无代码共用。

## 当前状态（2026-11-28）

| 部分 | 状态 |
|---|---|
| BSTP 协议编解码 | ✅ 已实现并自测通过（`core/bstp.py`） |
| 传输层 USB CDC / UDP | ✅ 已实现（`core/transport.py`），含字节流重同步 |
| 设备会话 / 周期槽 / 统计 | ✅ 已实现（`core/device.py`） |
| 模拟设备（无硬件可演示） | ✅ 已实现（`core/mock.py`），可按测试 DBC 产流量 |
| DBC / ARXML 运行时加载 | ✅ 已实现（`core/database.py`，基于 cantools） |
| 上位机 GUI | ✅ 已实现，Windows / Linux 双平台实测通过 |
| 命令行模式 | ✅ 已实现（`cli.py`） |
| **ESP32 固件** | 🧪 当前为 RGB 验证程序；BSTP 通道 ID/驱动接口骨架已建立，MCP2518FD 驱动与 BSTP 主固件尚未实现 |
| 以太网侧信号收发 | ❌ 界面与流程先行，固件未实现 |
| **工程文件（打开即用）** | ❌ **最大缺口**，配置全都不持久化（见 5.4） |

**版本号暂不启用** —— 等成品到一定规模再开始管理，届时上位机与固件
**分开管理、互不绑定**（固件版本由设备在 `HELLO_ACK` 上报，不写死在上位机）。

## 命名规范

设备全名 **ESP32-BusSpyTool**，项目文件夹 `BusSpyTool/`，
采用一致的项目命名风格。

| 场景 | 写法 |
|---|---|
| 设备/项目全名 | `ESP32-BusSpyTool` |
| 项目根 | `BusSpyTool/` |
| 固件 | `demo/fireware/`（ESP-IDF RGB 验证工程）；产品固件待实现 |
| GUI 入口 | `BusSpyTool/app.py` |
| CLI 入口 | `BusSpyTool/cli.py`，命令 `busspy` |
| 协议名 | **BSTP** v1 = **B**us **S**py **T**ool **P**rotocol |
| 协议 magic | `0x50545342` = `"BSTP"` (LE) |

```bash
python -m BusSpyTool.app                      # 开界面
python -m BusSpyTool.cli monitor --usb COM5   # 命令行
python -m BusSpyTool.tools.selftest           # core 自测，无需硬件
python -m BusSpyTool.tools.uitest --seconds 8 # UI 冒烟，无需硬件
```

---

## 0. 结论速览（先看这里）

| 问题 | 结论 |
|---|---|
| 当前阶段做什么 | 先实现 CAN-FD 1（MCP2518FD）；其余 4 路 CAN 和 W5500 先保留固定软件接口 |
| 最终 CAN 目标怎么扩展 | 3 路经典 CAN + 2 路 CAN-FD；S3 内置 1 个 TWAI，另 4 路 CAN 需外部控制器；资源/吞吐待验证 |
| 怎么接上位机 | ✅ **USB CDC 为主**。S3 原生 USB 可枚举为虚拟串口，免配 IP、不占 W5500 |
| ESP32-S3 能用有线以太网吗 | ⚠️ S3 **无内置 EMAC**，必须外挂 SPI 芯片（W5500）。**该口专用于被测网络** |
| 以太网拿来干什么 | ESP32 作被测网段上的**独立节点**，与被测 ECU 直接收发裸 UDP / SOME/IP 信号 |
| 上位机能解析 DBC / ARXML 吗 | ✅ 运行时解析（cantools），不是预生成类 |

### 已定选型

| 决策点 | 选择 | 影响 |
|---|---|---|
| **产品定位** | **独立仿 CANoe 工具，不依赖外部测试框架** | 当前不实现框架适配 |
| 上位机连接 | **USB CDC-ACM 为主**，Wi-Fi / 以太网为辅 | USB 是字节流，BSTP 靠 magic + payload_len 做流式重同步 |
| W5500 用途 | **专用于被测以太网**（接被测 ECU） | 不拿它接上位机，两张网互不干扰 |
| UDP 协议 | **自有 BSTP v1** | 带 magic/版本/序列号/批量帧，修正旧版协议的弱点（见 1.5） |
| 数据库 | **运行时加载 DBC / ARXML**（cantools） | 与框架的「离线生成 Python 类」完全不同路，见 5.3 |
| SOME/IP | 固件侧**本期不做**，先做裸 UDP 帧 | 界面与流程先行 |
| 目标平台 | 无 FlexRay 的区域架构（如 `PlatformA`） | 含 FlexRay 的旧平台不在本期范围 |
| 固件开发 | **ESP-IDF（当前在 macOS 配置）** | 烧录/调试使用 USB Serial/JTAG 或 USB-UART 串口 |
| 上位机 | **Python + ttkbootstrap**，Windows / Linux 双平台 |
| 数据库来源 | 用户提供且有权使用的测试库（ARXML / DBC），不随仓库分发 |

**核心取舍**：把「周期发送调度 + E2E 计算 + 硬件时间戳」全部下放固件，
用 MCU 的确定性降低 PC 侧调度抖动，见第 4.3 节。

> **第 1 节的旧版参考实现分析**用于说明 PC 与设备间的职责划分、协议行为及改进点；
> 本工具不复刻其协议。

---

## 1. 旧版参考实现分析（设计参考，非兼容目标）

### 1.1 参考实现概况

参考实现是 Linux x86-64 用户态程序，不是库或配置文件：

```
ELF 64-bit LSB pie executable, x86-64, dynamically linked, not stripped
reference_adapter                  dynamically linked, with debug symbols
NEEDED: CAN interface library, trace library, libpthread, libstdc++
RUNPATH: system and application-local library paths
```

结构信息可通过调试符号检查，无需反汇编。

职责：读取配置、打开 CAN 通道、执行周期发送与 E2E 计算、通过 UDP 与主机双向传输，并保存 ASC 日志。

启动方式：

```bash
sudo ./reference_adapter <config_path> <trace_path> <cycle_send_status>
# cycle_send_status: 0 = 启动即发周期报文, 1 = 只开 bus 不发
```

### 1.2 UDP wire format（主机 ↔ 参考实现）

端口在 ini 中配置，字段名沿用 FlexRay 前缀但 CAN 也走同一对端口：

| 方向 | 端口 | ini 键 |
|---|---|---|
| 主机 → 参考实现 | 8000 (`port - 1`) | `SRC_PORT` |
| 参考实现 → 主机 | 8001 (`port`) | `DST_PORT` |

**三种包靠「长度」区分**，无 magic、无版本号、无序列号：

```
主机 → 参考实现
  92 B  CAN_TX_REQUEST  CAN/CAN-FD 发送（单帧 or 周期）
 314 B  AUX_TX_REQUEST  其他总线帧（本方案不实现）
   8 B  FILTER_ENTRY    接收过滤表增删
参考实现 → 主机
  80 B  CAN_FRAME       收到的 CAN/CAN-FD 裸帧（无发送头）
>=308 B AUX_FRAME       其他总线帧
```

`CAN_FRAME` —— 80 字节，`_pack_ = 1`，**本方案固件必须严格字节对齐实现**：

```c
// offset  size  字段
//   0      1    u8  channel        通道号，从 0 开始
//   1      1    u8  properties     [7]错误帧 [6]已记录 [2]扩展帧 [1]远程帧 [0]方向 0=RX 1=TX
//   2      1    u8  dlc            *** DLC code 0..15，不是字节数 ***
//   3      1    u8  fd_properties  [2]ESI [1]BRS [0]EDL(1=FD帧)
//   4      4    s32 can_id         CAN ID
//   8      8    u64 timestamp_us   微秒时间戳
//  16     64    u8  data[64]
// 共 80 字节
```

`CAN_TX_REQUEST` —— 92 字节，发送时在 `CAN_FRAME` 前加 12 字节头：

```c
//   0      4    s32   hw_index     固定 0
//   4      4    f32   cycle_time   *** 单位：秒 ***
//                                  -1  = 停止该帧周期发送
//                                   0  = 发单帧
//                                  >0  = 按此周期硬件循环发送
//   8      4    s32   log_enabled  是否写 ASC
//  12     80    CAN_FRAME frame
```

`FILTER_ENTRY` —— 8 字节，接收过滤：

```c
//   0      4    s32 message_id  0 = 整条 bus，非 0 = 单条报文
//   4      1    u8  bus_type    0 = CAN, 1 = 其他总线
//   5      1    u8  channel     通道
//   6      1    u8  operation   0 = 删除指定, 1 = 增加, 2 = 清空全部
//   7      1    u8  reserved    保留
```

> **坑 1：`dlc` 是 DLC code 而非长度。** `DLC_DATA_BYTE_CNT = [0,1,2,3,4,5,6,7,8,12,16,20,24,32,48,64]`。
> 主机侧会把传入的字节数转成 code 再上线，
> 固件收到后必须反查表，否则 DLC=12 会被当成 12 字节（实际应为 24 字节）。
>
> **坑 2：无帧边界保护。** 一个 UDP 包一帧，靠长度分发。固件收到非 92/314/8 的长度必须丢弃并计数，
> 不要试图解析。

### 1.3 ini 配置格式（参考实现启动时读取）

```ini
[config]
E2EConfig      = 1
SaveLog        = 1
DeviceSerial   = A                   ; 设备序列号，用于多设备区分
E2ECRCDLL      = ./e2e_crc.dll
CRCFunc        = crc8_calc
SRC_IP         = 127.0.0.1
SRC_PORT       = 8000
DST_IP         = 127.0.0.1
DST_PORT       = 8001

[0100]                               ; section 名 = <通道2位><序号>，0100 = 通道 01 第 00 条
CANID       = 1343                   ; *** 十进制 ***
ISCANFD     = 0
CANFDBRS    = 0
ISSTD       = 1
CyclcTime   = 0.5                    ; 兼容此配置格式时需使用该字段名
CANLEN      = 8                      ; 字节数（这里是长度，不是 code）
ISWAKE      = 1
DATA        = 63,64,255,255,255,255,0,0   ; 十进制逗号分隔

[0101]
...
E2E_PROFILE = PROFILE_G
00 = 199,2,0,10503,0,0               ; 组 0 成员 0
01 = 191,4,0,10503,0,1               ; 组 0 成员 1
10 = 511,4,0,4379,0,1                ; 组 1 成员 0  ← 十位=组号，个位=组内序号
```

E2E 信号行格式：

```
<startBit>,<Length>,<IsIntel>,<DataId>,<SignalValue>,<is_cntr>
                                                      ^ 1 = 该信号是 rolling counter，由发送端自增
```

### 1.4 参考实现的数据结构（供固件设计对标）

```c
struct CycleEntry {              // 周期发送表条目
    u8    channel_index;
    float cycle_seconds;
    u8    precise;               // 精确周期模式开关
    s32   can_id;
    CAN_FRAME frame;
    vector<vector<E2ESignal>> signals;       // 按 E2E 组分桶
};

struct SignalDef {                // 信号位域描述
    s32 start_bit, bitlen, start_byte, end_byte, start_bit_in_byte;
    u8  is_intel, is_unsigned, signal_count;
    double factor, offset;
    u64 value;
};

struct E2ESignal {
    SignalDef signal;
    u8 data0, data1;
    u8 error_injection;          // E2E 故障注入标志
};

struct AdapterConfig {            // 对应 [config] 段
    u32 src_port, dst_port;
    u8  e2e_enabled, save_log;
    u16 max_static_slots;
    string src_ip, dst_ip, e2e_library, crc_function, device_serial;
};
```

关键职责（用于说明模块边界）：

```
周期发送引擎                                  硬件周期发送
配置解析                                      ini → 周期表
E2E CRC 与 rolling counter 更新               每次发送前回填
信号位解析与字节序转换                        数据编解码
CAN 收发回调                                  设备事件分发
UDP socket 管理                               主机与设备通信
日志写入                                      ASC 落盘
```

### 1.5 旧版实现的已知限制（新固件应当改进）

根据协议行为与台架测试记录：

| 缺陷 | 位置 | ESP32 版本对策 |
|---|---|---|
| **波特率写死在二进制里**，ini 不能配 | 旧版实现 | `CFG_SET` 下发波特率，NVS 持久化 |
| **无状态查询命令，不回总线负载** | 旧版实现 | 加状态心跳包（见 2.3） |
| 需要 `sudo` | 旧版实现 | 无（UDP 客户端不需要特权） |
| 多设备间进程管理相互影响 | 旧版实现 | 无进程模型，设备即硬件 |
| 无 RX 时间戳 | 旧版实现 | MCP2518FD 硬件 TBC 时间戳 |

---

## 2. BSTP 协议

### 2.1 外部框架集成：本期明确不做

本工具是独立的仿 CANoe 工具，当前不集成外部测试框架。
以下全部**不做**，留给以后：

- 不写外部框架的后端适配包
- 不依赖特定框架的总线接口或装配逻辑
- 不产出外部框架专用的数据对象

> 将来若要集成框架，可增加适配层，把 BSTP 帧转换成目标框架的数据结构。
> **但那是另一件事，不影响本工具当前的任何设计。**

### 2.2 自有协议 BSTP v1

**决策：设计自有协议 BSTP（Bus Spy Tool Protocol），不复刻任何现有 wire format。**

旧版协议的弱点（第 1.2 节）在自有协议里全部修掉：

| 旧版问题 | BSTP 对策 |
|---|---|
| 三种包靠长度裸分发，无 magic / 版本号 | 12 字节定长头，含 magic + version + msg_type |
| 一个 UDP 包只装一帧 | **批量帧**，一包最多装 60 帧（见下方包率分析） |
| `FDLC` 是 DLC code，极易误解析 | `len` 直接是**实际字节数** |
| 无序列号，控制命令不可靠 | `seq` 字段，请求/响应可配对 |
| 无状态查询、不回总线负载 | `STAT` 消息类型 |
| 80 字节定长，8 字节帧也占满 | 变长 payload，8 字节帧仅占 24 字节 |

#### 包头（12 字节，小端）

ESP32-S3 与 x86_64 都是小端，**全协议统一小端可做到零字节序转换**。

```c
typedef struct __attribute__((packed)) {
    uint32_t magic;        // 0x50545342  = "BSTP" (LE)
    uint8_t  version;      // 1
    uint8_t  msg_type;     // 见下表
    uint16_t seq;          // 请求/响应配对；事件类为自增计数，用于丢包检测
    uint16_t payload_len;  // 后续字节数
    uint8_t  flags;        // [0] need_ack  [1] more_fragments
    uint8_t  reserved;     // 0
} bstp_hdr_t;              // sizeof == 12
```

#### 消息类型

```
PC → 设备                          设备 → PC
0x01 HELLO          握手            0x81 HELLO_ACK   设备信息(serial/fw_ver/能力位)
0x02 CFG_SET        配置下发        0x82 CFG_ACK
0x10 TX_FRAME       发帧(可批量)    0x90 RX_FRAME    收帧(批量)
0x11 CYC_SET        周期表增删改    0x91 STAT        状态心跳 1Hz
0x12 FILTER_SET     过滤表          0x9F ERROR       错误上报
0x13 CTRL           控制命令
```

`CTRL` 子命令：`START` / `STOP` / `RESET` / `BUS_ON` / `BUS_OFF` / `WIFI_ON` / `WIFI_OFF` /
`CYC_START` / `CYC_STOP` / `E2E_FAULT`。

#### 帧记录（TX / RX 共用，变长）

```c
typedef struct __attribute__((packed)) {
    uint64_t ts_us;        // 微秒时间戳。RX = MCP2518FD 硬件 TBC；TX = 实际发出时刻
    uint32_t can_id;       // [28:0] ID, [31] IDE 扩展帧, [30] RTR, [29] ERR
    uint8_t  chn;          // BSTP endpoint ID; 0-2 retain legacy meanings, 3-5 are appended
    uint8_t  len;          // *** 实际字节数 0..64，不是 DLC code ***
    uint8_t  flags;        // [0] FD  [1] BRS  [2] ESI  [3] dir(0=RX,1=TX)
    uint8_t  reserved;
    uint8_t  data[];       // len 字节，后补 0 对齐到 4 字节边界
} bstp_frame_t;            // 头 16 字节 + 对齐后的 data
```

#### 周期表记录（`CYC_SET`）

```c
typedef struct __attribute__((packed)) {
    uint16_t slot_id;      // 槽位号，上位机分配并持有
    uint32_t period_us;    // 0 = 删除该槽
    uint16_t e2e_cfg_idx;  // 0xFFFF = 无 E2E
    uint8_t  precise;      // 精确周期模式，忙等保抖动
    uint8_t  reserved;
    bstp_frame_t frame;
} bstp_cyc_t;
```

> **周期表用「槽位 + 增量更新」语义**，不是整表重下。
> 改一条报文的 data 只发一条 `CYC_SET`，固件原地改槽，**不重置 `next_due_us`** ——
> 保证「改值不扰乱相位」，这是时序类用例的语义要求。

#### 为什么必须批量：包率是真瓶颈

| 场景 | 旧版格式（1 帧/包） | BSTP（批量） |
|---|---|---|
| 8 字节帧 @ 500 kbps 满载 ≈ 4000 帧/s | 4000 包/s，3.9 Mbps | **67 包/s**，0.8 Mbps |
| 64 字节 FD 帧 @ 2 Mbps 满载 ≈ 2800 帧/s | 2800 包/s，2.7 Mbps | 156 包/s，1.9 Mbps |

一包上限：MTU 1500 − 20 (IP) − 8 (UDP) = 1472 字节 payload，
减去 12 字节头后 **8 字节帧可装 60 条**（每条 24 字节）。

**带宽只省 ~4.8 倍，但包率降到 1/60 —— 后者才是关键。**
W5500 只有 ~10 Mbps，且每个 UDP 包在 lwIP + W5500 SPI 事务上都有固定开销；
ESP32-S3 处理 4000 pps 会直接吃掉一个核，而 67 pps 几乎无感。
这是批量设计的真正理由，不是过度优化。

#### 聚合策略（延迟 vs 效率）

批量会引入等包延迟，所以用**双触发刷新**：

```
凑满 MTU            → 立即发
或 1 ms 聚合窗口到期 → 立即发（窗口可配，CFG_SET 下发）
```

1 ms 聚合窗口对最小 10 ms 周期的用例判定无影响（误差 < 10%），
但把包率压到了可接受范围。若后续有严格时延场景，窗口可配到 0（退化为一帧一包）。

#### 状态心跳（`STAT`，1 Hz）

```c
typedef struct __attribute__((packed)) {
    uint64_t uptime_us;
    uint32_t rx_frames, tx_frames, rx_drop, tx_fail;
    uint32_t cyc_slots_active, cyc_miss;     // cyc_miss 必须暴露，见 4.3
    uint32_t jitter_p99_us;                  // 周期引擎实测抖动
    uint16_t bus_load_permille;              // 总线负载 ‰
    uint8_t  err_state;                      // 0 ACTIVE 1 WARN 2 PASSIVE 3 BUSOFF
    uint8_t  tec, rec;                       // MCP2518FD CiTREC 寄存器
    uint8_t  link_up, wifi_up;
} bstp_stat_t;
```

> 这把旧版实现「不回总线负载、无状态查询」的两个缺陷一次补上。
> `cyc_miss` 与 `jitter_p99_us` 是第 7 节 P2 验收判据的数据来源 —— 设备自己报告时序质量。

---

## 3. 硬件可行性裁决

### 3.1 上位机连接：USB CDC 为主

ESP32-S3 同时提供通用 USB-OTG 和固定功能的 USB Serial/JTAG 控制器。USB Serial/JTAG 可枚举为 CDC-ACM 虚拟串口，esptool 也可通过它进入下载模式；实际应用的 BSTP 链路可使用 USB CDC。这些串口通信不等同于 USB 大容量存储：

| | 规格 | 说明 |
|---|---|---|
| USB 版本 | **USB 2.0 Full-Speed（12 Mbps）** | **不是 High-Speed，更不是 USB 3.0** —— S3 的 USB 外设就是 FS |
| CDC 目标有效带宽 | ~500–900 KB/s | 8 字节帧在 BSTP 上占 24 字节 → 理论 2 万帧/s 以上，远超 CAN 物理层上限；尚未在本板实测 |
| 延迟 | 低且稳定 | USB 层自带重传，无网络抖动、无丢包 |
| 配置 | 免配 IP | Windows 认作 COM 口，Linux 为 `/dev/ttyACM*`，**两边都原生支持，不用装驱动** |
| 供电 | 同一根线 | 调试时不用额外电源 |

**选 CDC-ACM 而不是 USB-ECM / RNDIS**：后者能让 USB 变成网卡、BSTP 零改动跑 UDP，
但 ECM 在 Windows 上要装驱动、RNDIS 在 Linux 上有坑，跨平台一致性差。

本板实测通过 USB Serial/JTAG 用 esptool 读取 16 MB 闪存：默认 115200 设置下约 25 分钟；提高到 460800 时出现串口数据错误。此结果反映闪存备份命令，不代表应用运行时 CDC 吞吐。

代价：**CDC 是字节流，没有包边界**。好在 BSTP 头自带 magic + payload_len，
可以直接做流式重同步（`core/transport.py:SerialTransport._extract`），
不需要 SLIP / COBS 转义开销。已实测：垃圾前缀、逐字节到达、假 magic、缓冲有界四种情况全部通过。

### 3.2 W5500 专用于被测以太网

**ESP32-S3 没有内置以太网 MAC**（原版 ESP32 有 RMII EMAC，S3 取消了），
常见的 LAN8720 方案在 S3 上**不可用**。有线以太网只有一条路：SPI 芯片。

| 方案 | 实测吞吐 | 成本 | 评价 |
|---|---|---|---|
| **W5500 over SPI** | ~8–15 Mbps | ¥15–30 | ✅ **已选**。IDF `esp_eth` 驱动成熟，被当纯 MAC 用走 lwIP，支持多播（SOME/IP-SD 需要） |
| DM9051 over SPI | ~10–20 Mbps | ¥20–35 | 备选，货源少些 |
| ENC28J60 | 10 Mbps 半双工，实测 <5 Mbps | ¥10 | ❌ 不用，IDF 驱动有已知限制、多播支持差 |

**关键：这个口不拿来接上位机。** W5500 保留为被测网络口（接被测 ECU 收发 SOME/IP / 裸 UDP 信号，见第 6 节），
管理链路走 USB。当前阶段先实现一颗 MCP2518FD；完整产品的五路 CAN 与 W5500 会竞争有限的 SPI 总线时隙，
控制器分组及吞吐必须结合 V1.4 板级资料和验收负载验证，不能从单路联调结果推断完整产品能力。

### 3.3 Wi-Fi：辅助用途

Wi-Fi 是 S3 内置的，不用也在硅片上。它不是主连接，但有几个实在的用途：

| 用途 | 价值 | 说明 |
|---|---|---|
| **OTA 固件升级** | 高 | `esp_https_ota`。**让烧录变成一次性问题** —— 首次在 Linux 上烧，之后永不碰串口。16 MB flash 做双 app 分区很宽裕 |
| 无线调试 | 中 | 设备装在机柜里或车上不便接 USB 时，BSTP 照样能跑（`UdpTransport`） |
| 带外状态查询 | 中 | USB 线被拔时还能连上看 `STAT` |
| 首次配置（SoftAP） | 中 | 配被测网段 IP 不必接串口 |

> **Wi-Fi 下时序依然可信。** 因为
> ① **时间戳是固件侧 MCP2518FD 硬件 TBC 打的**，Wi-Fi 抖动只影响「上位机什么时候收到」，
> 不影响「事件何时发生」的记录精度；
> ② **周期发送调度在固件本地**（4.3 节），Wi-Fi 断续也不会让周期帧失准。
>
> 真正受影响的只有「需要上位机在严格时限内**响应**」的场景
> （如「收到 A 帧后 5 ms 内必须发 B 帧」）—— 那种场景走 USB。

> **关键约束：Wi-Fi 常开会破坏第 4.2 节的双核隔离。**
> ESP-IDF 的 Wi-Fi 任务优先级 23（高于本方案除 `cyc_tx_task` 外的全部任务），
> 且协议栈默认钉在 core 0，会与 lwIP + SPI 争抢；射频噪声对开发板杜邦线联调时的
> SPI 信号完整性也有实际影响。
> **结论：Wi-Fi 默认关闭，按需开启**（`CTRL_WIFI_ON`），状态存 NVS。

### 3.4 引脚约束（N16R8 特有坑）

**N16R8 的 8 MB PSRAM 是 Octal 模式，占用 GPIO 33–37。** 这几个脚在本方案中**不可用**，
分配 SPI 引脚时必须避开，否则上电即 PSRAM 初始化失败或 SPI 工作异常。

PSRAM / flash 走的是内部 SPI0/SPI1，**不占用** SPI2/SPI3，所以 3.5 节的两路 SPI 分配依然成立。

当前开发板联调接线中 MCP2518FD 使用 GPIO 9–13；新款 0.96 英寸 I2C OLED 使用 GPIO 8（SCL）和 GPIO 7（SDA），
这只是开发板接线记录，不代表产品针脚分配。显示屏的针脚识别、供电注意事项和联调接线图见
[ESP32-S3、MCP2518FD 与 OLED 硬件针脚说明](./HARDWARE_PINOUT.md)和
[OLED 接线说明](./OLED接线说明.md)。新款资料标注 SSD1315，控制器兼容性与当前 I2C 地址仍需上电测试/扫描后确定固件配置。

**产品边界：3 路经典 CAN + 2 路 CAN-FD + W5500。** 按实施阶段先交付 CAN-FD 1；上位机和固件已固定六个 BSTP endpoint ID，并提供 CAN 控制器与 Ethernet 分离的接口骨架。GPIO/SPI 的具体分配须对照 2025-V1.4 板级资料并完成资源核算后再冻结；开发板联调接线不作为产品针脚表。

### 3.5 SPI 资源分配

ESP32-S3 可用通用 SPI 控制器 **2 个**（SPI2/GPSPI2、SPI3/GPSPI3）。当前只规划单个 CAN-FD 控制器；最终目标涉及 4 个外部 CAN 控制器和 W5500，多个 SPI 外设需共享总线并独立片选/中断：

```
SPI host(s) ──► MCP2518FD #1                 (当前阶段 CAN-FD 1)
              ├─ CAN-FD #2 外部控制器      (预留)
              ├─ CAN2.0B #2/#3 外部控制器  (预留)
              └─ W5500                      (预留，被测网络)
TWAI ─────────► CAN2.0B #1                  (预留)
```

图示只表达功能分工，不冻结 GPIO 或 SPI host 分组。共享 SPI 会串行化事务，最终方案必须压测双 FD、经典 CAN、W5500 与 USB 上传的组合负载；若无法满足目标，应调整主控/控制器架构，而不是重排已发布的 endpoint ID。

### 3.6 开发验证物料与产品 BOM 边界

下表记录当前开发验证所用物料和候选器件，不是产品 BOM，也不冻结产品器件型号、封装或 PCB 方案。产品 BOM 需在控制器架构、接口保护、电源预算和并发性能验证后另行确定。

| 件 | 型号 | 数量 | 备注 |
|---|---|---|---|
| 主控 | ESP32-S3 N16R8 DevKit | 1 | 已有。16 MB flash / 8 MB PSRAM |
| CAN-FD 控制器 | MCP2518FD 模块 | 1 | 已有。确认模块是否已带收发器 |
| CAN-FD 收发器 | TJA1051T/3 或 MCP2562FD | 1 | 若模块未集成则需外加 |
| 以太网 | W5500 模块 | 1 | **需增购**（3.1 节决策点） |
| CAN 2.0 收发器 | SN65HVD230 模块 | 1 | 开发验证候选；产品每路需独立配置收发器 |
| 状态显示屏 | 新款 0.96 英寸 I2C OLED（JMD0.96D-I） | 1 | 用户已有；3.3 V 供电；GPIO 8/7 仅为当前开发板联调接线 |
| 终端电阻 | 120 Ω | 2 | 可跳线切换 |
| 晶振 | MCP2518FD 模块自带 40 MHz | — | **必须 40 MHz**，20 MHz 算不出 8 Mbps |

> **坑：MCP2518FD 的 40 MHz 晶振是硬要求。** 位时序表按 40 MHz 推导；20 MHz 晶振下
> 数据段最高只能到 4 Mbps 且采样点不理想。购买时确认模块丝印。

### 3.7 关键能力对照

| 能力 | MCP2518FD | ESP32-S3 TWAI | 参考实现 | 结论 |
|---|---|---|---|---|
| CAN-FD | ✅ 8 Mbps | ❌ 无 | ✅ | FD 走 MCP2518FD |
| CAN 2.0 | ✅ | ✅ 1 Mbps | ✅ | 预留通道走 TWAI |
| **硬件 RX 时间戳** | ✅ 32-bit TBC，可配预分频 | ❌ 无 | ✅ | 填 `FTimeUs` 的来源 |
| **硬件周期发送** | ❌ 无 | ❌ 无 | ✅ | **必须固件软调度**（4.3） |
| 接收过滤器 | ✅ 32 个 filter/mask | ✅ 1 组 | ✅ | 支撑 `TPASSMSGINFO` |
| 发送 FIFO | ✅ 可配，含 TXQ 优先级 | 32 帧 | — | 突发缓冲 |

> **TBC 是 32 位，@1 µs 约 71.6 分钟溢出。** 固件必须做 64 位软扩展
> （检测回绕 + 累加高 32 位）才能填满 `u64 FTimeUs`，否则长稳用例跑过 1 小时时间戳跳变。

---

## 4. 固件设计（ESP-IDF v5.x，C）

### 4.1 模块划分

```
BusSpyTool/firmware/
├── main/
│   ├── main.c                 启动、NVS、网络起栈、任务创建
│   ├── net_link.c/h           netif 抽象：esp_eth(W5500) / esp_wifi 二选一，BSTP 之下透明
│   ├── mgmt.c/h               带外管理 + esp_https_ota（Wi-Fi 默认关，见 3.3）
│   ├── bstp.c/h               BSTP v1 编解码 + 批量拆装包 + 聚合刷新（见 2.3）
│   ├── busspy_interfaces.h/c  固定 endpoint ID、CAN 驱动接口、独立 Ethernet 数据报接口
│   ├── canfd_mcp2518.c/h      CAN-FD 1 的 SPI 驱动、位时序、FIFO、TBC 时间戳扩展
│   ├── can_classic_twai.c/h   CAN 2.0B 1 的 TWAI 驱动（预留）
│   ├── can_external.c/h       CAN-FD 2 与 CAN 2.0B 2/3 的外部控制器适配（预留）
│   ├── cyc_engine.c/h         周期发送调度器（本方案核心，CAN 与裸 UDP 帧共用）
│   ├── e2e.c/h                crc8 / Profile 4 / 11 / G + rolling counter
│   ├── eth_udp.c/h            arxml 定长裸 UDP 帧收发（见 6.3）
│   ├── cfg_store.c/h          CFG_SET 配置持久化到 NVS（不再解析 ini）
│   └── stats.c/h              帧计数、总线负载、错误状态、抖动统计
└── sdkconfig.defaults
```

### 4.2 任务与核心绑定

| 任务 | 核 | 优先级 | 职责 |
|---|---|---|---|
| `cyc_tx_task` | 1 | 20 (最高) | 周期发送调度，**绝不被网络阻塞** |
| `can_rx_task` | 1 | 18 | MCP2518FD 中断 → 读 FIFO → 入 ringbuffer |
| `bstp_rx_task` | 0 | 12 | BSTP 收 → 解析 → 单帧发送 / 更新周期槽 / 改过滤 |
| `bstp_tx_task` | 0 | 10 | ringbuffer → **批量聚合**（满 MTU 或 1 ms 窗口）→ 发上位机 |
| `stats_task` | 0 | 5 | 1 Hz `STAT` 心跳 |

**核心隔离是刻意的**：网络栈（lwIP + W5500 SPI）的不确定延迟不能传染周期发送时序。
CAN 侧与网络侧之间只用 `RingbufferHandle_t`（无锁）通信。

> 这也是 3.2 节「Wi-Fi 默认关闭」的原因：Wi-Fi 协议栈默认钉在 core 0 且任务优先级 23，
> 开启后会与 lwIP + W5500 SPI 在 core 0 上三方争抢，并抢占 `bstp_*` 任务。
> `cyc_tx_task` 在 core 1 且优先级最高，是唯一不受影响的。

### 4.3 周期发送引擎（最关键，直接针对已知失败根因）

> 背景：旧版实现的周期用例曾失败，根因两层 ——
> ①「时基漂移」：用 `上次发送时刻 + 周期` 累加，误差单向累积；
> ②「server 自身开销」：调度点被业务逻辑挤占。
> 固件方案必须在设计上消掉这两层。

```c
typedef struct {
    uint32_t id;
    uint8_t  dlc_code;
    uint8_t  data[64];
    uint8_t  flags;              // FD / BRS / ext
    uint32_t period_us;          // 0 = 停用
    int64_t  next_due_us;        // 绝对时间基准，不是增量
    bool     precise;            // 精确周期模式
    e2e_cfg_t *e2e;              // NULL = 不算 E2E
} cyc_slot_t;

static cyc_slot_t g_slots[CYC_MAX_SLOTS];   // 建议 128

void cyc_tx_task(void *arg)
{
    const int64_t t0 = esp_timer_get_time();
    for (;;) {
        int64_t now = esp_timer_get_time();
        int64_t earliest = INT64_MAX;

        for (int i = 0; i < CYC_MAX_SLOTS; i++) {
            cyc_slot_t *s = &g_slots[i];
            if (!s->period_us) continue;

            if (now >= s->next_due_us) {
                if (s->e2e) e2e_apply(s->e2e, s->data);   // CRC + rolling counter
                mcp2518_transmit(s);

                // 关键：绝对时间推进，不是 next = now + period
                s->next_due_us += s->period_us;
                // 落后超过一个周期则重新对齐，避免补发风暴
                if (s->next_due_us < now) {
                    int64_t n = (now - s->next_due_us) / s->period_us + 1;
                    s->next_due_us += n * s->period_us;
                    stats_inc_cyc_miss(i);                // 必须暴露给上位机
                }
            }
            if (s->next_due_us < earliest) earliest = s->next_due_us;
        }

        int64_t sleep_us = earliest - esp_timer_get_time();
        if (sleep_us > 1000) {
            vTaskDelay(pdMS_TO_TICKS(sleep_us / 1000));   // 粗睡
        } else if (sleep_us > 0) {
            esp_rom_delay_us(sleep_us);                   // 细等，换抖动
        }
    }
}
```

设计要点：

1. **绝对时间基准** `next_due_us += period_us`，不用 `now + period`。消除漂移偏置累积。
2. **`esp_timer_get_time()` 是 64 位 µs 单调时钟**，不回绕，直接作为时基。
3. **miss 必须上报**，不能静默。`stats_inc_cyc_miss()` 进状态心跳，上位机能看到真实时序质量。
4. **粗睡 + 细等混合**：>1 ms 用 `vTaskDelay` 让出 CPU，<1 ms 用忙等保抖动。
   预期抖动 **±50 µs 量级**，优于 Python 侧调度 2–3 个数量级。
5. **最小周期取 10 ms 为设计目标**。全仓 CAN 用例最小周期实测为 10 ms
   （曾出现的 5 ms 那条属 FlexRay，不在本方案范围）。不要为 1 ms 过度设计。

### 4.4 MCP2518FD 位时序

40 MHz 晶振，内部 PLL 可倍频到 80 MHz。以 500 kbps 仲裁段 / 2 Mbps 数据段为例：

```
SYSCLK = 40 MHz（不开 PLL）
仲裁段: BRP=0, TSEG1=62, TSEG2=15, SJW=15  → 40M/(1*(1+63+16)) = 500 kbps，采样点 80%
数据段: BRP=0, TSEG1=14, TSEG2=5,  SJW=5   → 40M/(1*(1+15+ 4)) = 2 Mbps，采样点 80%
```

**TDC（Transmitter Delay Compensation）在数据段 ≥1 Mbps 时必须开**，否则 BRS 帧误码。
`CiTDC.TDCMOD = 2`（自动测量）。

波特率表做成固件常量数组，由 `CFG_SET` 在运行时选择并存 NVS —— 避免波特率写死在固件中。

### 4.5 E2E

E2E 配置通过 `CFG_SET` 下发并由固件存入 NVS。支持 `PROFILE_G`、Profile 4 / 11。
CRC 算法按各 Profile 定义实现：

```
crc8_calc / profile11_crc8 / profile4_crc32
```

固件侧 `e2e_apply()` 在**每次硬件发送前**回填 CRC 与 rolling counter，
每次硬件发送前回填 CRC 与 rolling counter。故障注入能力通过 `CTRL/E2E_FAULT` 提供。

### 4.6 ASC 日志落点

参考实现由主机写 ASC。ESP32 无文件系统容量做长稳 trace
（16 MB flash 扣掉固件后不足，且写 flash 会干扰时序）。

**决策：ASC 落盘放上位机。** 固件只负责带上准确的 `ts_us`，
上位机复用 `usbcan_server.py` 里的 `AsyncASCLogger` 写文件。
BSTP 刻意**不设**日志标志字段——
记不记录是上位机单方面的决定，不该占用线上带宽。

---

## 5. 上位机软件设计

### 5.0 平台矩阵：固件开发 Linux，上位机双平台

**两件事的平台约束完全不同，别混为一谈：**

| 场景 | Windows | Linux / macOS | 说明 |
|---|---|---|---|
| **固件开发 + 烧录** | ❌ 不作为主要开发环境 | ESP-IDF + esptool（当前在 macOS 配置，尚未完成验证） | 烧录使用 USB Serial/JTAG 或 USB-UART 串口 |
| **上位机（GUI + CLI）** | ✅ 实测通过 | ✅ 实测通过 | 连设备是 USB CDC 或 UDP，与 OS 无关 |

实测记录：

| 平台 | 环境 | 结果 |
|---|---|---|
| Windows 11 | Python 3.14，ttkbootstrap 2.0.1 | GUI 300 帧/s 流畅；串口枚举正常 |
| Ubuntu 22.04 | Python 3.10.12，X11 `:1`，2560×1440 | GUI 360 帧/s 流畅；`/dev/ttyS4` 枚举正常；core 自测全绿 |

#### 设计约束：保持零 POSIX 依赖

上位机全部模块**刻意不用任何平台专有 API**，这样两边同一份代码：

```
core/bstp.py        只用 struct / dataclasses
core/transport.py   只用 socket / threading / pyserial
core/database.py    只用 cantools
ui/*                tkinter / ttkbootstrap
```

平台差异只在三处，且都已处理（见 `ui/__init__.py`）：

| 差异点 | Windows | Linux |
|---|---|---|
| 窗口图标 | `.ico` + `wm_iconbitmap`（要设两次） | `.png` + `iconphoto`（X11 的 Tk 不认 .ico，要 XBM） |
| 任务栏图标 | 需设 `AppUserModelID` | 不需要 |
| DPI / 标题栏配色 | per-monitor v2 + DWM 属性 | 不需要 |

> **不要**在 `core/` 里引入 `fcntl`、`SO_REUSEPORT`、`/proc` 读取或 `subprocess` 调 shell。
> 一旦引入，Windows 侧就废了。
> （参照：主仓库的 `inter_sdk/tools/someip_py/client.py:86` 就用了 `SO_REUSEPORT`，
> 那是它只跑 Linux 的原因之一。）

#### OTA 让烧录成为一次性问题

首次烧录在 Linux 上做，之后**固件升级全部走 Wi-Fi OTA**（`esp_https_ota`，见 3.3 节）。
这意味着 Windows 用户**永远不需要碰串口** —— 拿到设备只需知道它的 IP。

> **烧录约束：禁止整片 Flash 擦除（如 `idf.py erase-flash`）。Wi-Fi 配置保存在 NVS，后续固件升级必须保留 NVS 分区并保持分区布局兼容，确保配置一次后通过 Wi-Fi 监听 Bus 不必重复配置。**

#### 固件开发与烧录环境

建议使用 Ubuntu 22.04 或其他受支持的 Linux 开发机：

```bash
# ESP-IDF v5.x
git clone -b v5.3 --recursive https://github.com/espressif/esp-idf.git ~/esp-idf
~/esp-idf/install.sh esp32s3 && . ~/esp-idf/export.sh

# 串口权限（一次性）
sudo usermod -aG dialout $USER
idf.py set-target esp32s3 && idf.py build
idf.py -p /dev/ttyACM0 flash monitor     # 内置 USB-Serial-JTAG
idf.py -p /dev/ttyUSB0 flash monitor     # CH340 / CP2102 UART 口
```

### 5.1 实现分层

本工具是独立程序，没有「适配层」这回事 —— BSTP 帧就是上位机的原生数据结构，
不需要转成任何框架的对象。实际实现如下（**已全部落地**）：

```
BusSpyTool/
├── app.py              GUI 入口（薄壳）：无参开界面，带参转 cli
├── cli.py              命令行：ports / monitor / send / cyc / stat / selftest
├── paths.py            路径解析唯一出口（含 PyInstaller _MEIPASS）
├── config/app_meta.py  元信息。版本号暂不启用
├── core/               不碰界面，无 X 的机器上也能用
│   ├── bstp.py         BSTP v1 编解码（Packet / Frame / CycSlot / Stat）
│   ├── transport.py    Transport 抽象 + UdpTransport + SerialTransport
│   ├── device.py       设备会话：收发线程、周期槽、状态轮询、帧分发
│   ├── mock.py         模拟设备，可按测试 DBC 产流量
│   ├── database.py     DBC / ARXML 运行时加载与信号编解码（cantools）
│   └── tracebuf.py     环形缓冲 + 按 ID 聚合（性能关键，见 5.3）
├── ui/                 只调 core
│   ├── main_window.py  菜单条 / 工具栏 / 数据库树 / 页签 / 状态栏
│   ├── trace_page.py   Trace（固定聚合 + 滚动双模式）
│   ├── graph_page.py   信号波形（Canvas 自绘）
│   ├── send_page.py    单帧 / 周期发送
│   ├── signal_page.py  信号监控
│   ├── stat_page.py    统计（设备侧 vs 上位机侧分开显示）
│   ├── eth_page.py     以太网 / SOME/IP（界面先行）
│   └── log_page.py     日志
├── utils/logger.py
├── tools/
│   ├── selftest.py     core 自测，无需硬件
│   └── uitest.py       UI 冒烟 + 截图，无需硬件
└── docs/DESIGN.md      本文
```

数据流：

```
USB CDC / UDP
  → transport.py   流式重同步 or 数据报 → [Packet, ...]
  → device.py      分发 RX_FRAME / STAT，批量投递给 listener
  → tracebuf.py    环形缓冲 + 按 ID 聚合（接收线程只做记账，不解码）
  → ui 各页        UI tick 批量渲染；信号解码**按需**（只解可见/被监视的）
```

**线程边界**：`device` 的 listener 在接收线程里被调用，**绝不碰 Tk 控件**。
UI 侧统一在 `main_window._tick()`（100 ms）里批量取数据、批量渲染。

硬件依赖通过抽象隔离，便于无硬件自测：

```python
class Transport(abc.ABC):          # core/transport.py
    def open(self) -> bool: ...
    def close(self): ...
    def send(self, packet: Packet) -> bool: ...
    def recv(self, timeout: float) -> List[Packet]: ...
```

`MockDevice` 与 `Device` 是鸭子类型等价的，UI 不需要知道连的是真设备还是模拟器。

### 5.2 命令行模式与冒烟测试（**Windows / Linux 通用**）

`cli.py` **只 import core，绝不 import ui** —— 无 X 的机器上 import tkinter 就会失败，
而台架机 / SSH 正是这个模式的主要用途：

```
BusSpyTool/cli.py        子命令：ports / monitor / send / cyc / stat / selftest
BusSpyTool/tools/        selftest.py（core 自测）、uitest.py（UI 冒烟 + 截图）
```

典型用法（Windows / Linux 相同）：

```bash
python -m BusSpyTool.cli ports                                  # 列出串口
python -m BusSpyTool.cli monitor --usb COM5                     # 实时帧流
python -m BusSpyTool.cli send --usb COM5 --id 123 --fd --data "00 11 22"
python -m BusSpyTool.cli cyc  --usb COM5 --id 123 --period 10   # 周期发送
python -m BusSpyTool.cli stat --usb COM5                        # 设备状态
python -m BusSpyTool.tools.selftest                             # core 自测
python -m BusSpyTool.tools.uitest --seconds 8 --shot out.png    # UI 冒烟
```

> `tools/uitest.py` 用模拟设备把界面完整跑起来并截图，**不需要任何硬件**。
> 这是 W5500 到货前、固件写好前唯一能做的 UI 回归。

### 5.3 上位机性能：实测与架构取舍

**上位机主体是 Python**（ttkbootstrap）。
关于「Python 会不会太慢」，先算账再决定。

#### 与测试框架的根本区别：这里是运行时解析

| | 离线生成型测试框架 | **本工具** |
|---|---|---|
| 数据库 | 预编译 Python 类，运行时只 import | **运行时**加载任意 DBC / ARXML（cantools） |
| 解析何时发生 | 从不 —— 运行时只是 `import` | 每次打开数据库 |
| 信号解码 | 预生成类内联了 `mask`/`shift` | cantools 的 `decode_message` |

所以「解析 arxml/dbc 慢不慢」在本工具里**是真问题**（在框架里不是）。
使用测试数据库验证报文与信号解析；单文件加载耗时在百毫秒量级，
**打开数据库是一次性动作，不在热路径**。

#### 真瓶颈是 UI 渲染架构，不是语言

```
USB CDC FS 实测带宽        ~800 KB/s
8 字节帧在 BSTP 上占       24 字节      → 理论 33,000 帧/s
CAN 物理层上限（500k,8B）  ~4,000 帧/s  ← 先于链路和 Python 成为瓶颈
Python struct.unpack       ~1-2 us/帧   → 4000 帧/s 约占 0.8% CPU
cantools 全量解码          ~75 us/帧    → 4000 帧/s 约占 30% CPU  ← 唯一的真开销
```

结论：**只要不无脑全量解码，Python 绰绰有余。** CANoe 自己也不全量解码。

#### 已采取的四条架构措施

1. **Trace 固定模式（按 ID 聚合）是默认**。行数 = 总线上唯一报文数（几十到几百），
   **不随时间增长**。滚动模式限 5,000 行 —— Treeview 过万行会明显迟钝，这是控件的限制。
2. **惰性解码**。只解码「展开的 Trace 行」「被监视的信号」「波形图订阅的报文」。
   监视 20 个信号就只解那几条报文，与总线帧率无关。
3. **批量 UI 刷新**。`main_window._tick()` 100 ms 一次，一次最多渲染 2,000 行（`drain_pending` 的刹车），
   且**只刷新当前可见页**，隐藏页不渲染。
4. **波形按像素降采样**。60 秒窗口 × 10 ms 周期 = 6,000 点，画布才 ~900 像素，
   每像素取一个点即可。

#### 实测结果

| 平台 | 帧率 | 结果 |
|---|---|---|
| Windows（Python 3.14） | 300 帧/s × 10 s | 界面流畅，UI tick 48 次，聚合 20 行 |
| Linux（Python 3.10，2560×1440） | 360 帧/s × 10 s | 同上，渲染无卡顿 |

#### 若将来实测仍是瓶颈

```
① numpy 向量化批量解码     ← 优先。BSTP 批量包天然适配
② Cython 编译解码热点      ← 改动小，保留 Python 语义
③ pybind11 C++ 扩展       ← 收益最大，但要维护构建
```

**C++ 扩展的正确落点是「一次处理一整批」而不是「解析一帧」**：一次调用处理
60 帧 × 约 30 信号 = 1800 个信号，跨语言调用开销被摊薄到可忽略。
按「每帧调一次」写，pybind11 的调用开销会吃掉大部分收益 —— 这是最常见的误用。

> 技术栈上没有障碍：项目中已有 ELF 解析器说明「C/C++ 编译成 .so 给 Python 调」可行。
> **在拿到实测瓶颈数据之前不要动手写 C++ 扩展。**

### 5.4 工程文件：打开即用（**待实现，优先级高**）

仿 CANoe 的 **Configuration** —— 用户把总线网络、数据库、常用收发项配好存成一个工程，
下次双击打开就能干活，不用重配一遍。

**这是当前最大的缺口**：现在数据库、发送列表、波形曲线、监控信号全都不持久化，
关掉程序就没了。

#### 核心设计原则：工具只提供机制，业务含义由用户配置表达

这条决定了很多东西**不该**写进代码：

> 比如诊断或参数写入，不做成内置功能模块。它本质上就是用户在发送列表里
> 配了几条固定报文、起个名字叫「测试请求」而已 —— 和「发一条唤醒帧」没有区别。
> 工具要做的是让这种配置**存得下、打得开、点一下就发**，
> 而不是为每种业务写一个专用面板。
>
> 同理：故障注入、唤醒序列、下电流程 —— 全是用户配出来的发送项组合。

判据：**如果一个功能只对某个项目/某个 ECU 有意义，它就该是配置而不是代码。**

#### 工程里存什么

```jsonc
{
  "version": 1,
  "name": "台架冒烟测试",
  "databases": [
    {"path": "path/to/your/test.dbc", "channel": 0}
  ],
  "device": {
    "mode": "usb", "target": "COM5",
    "canfd": {"arb_baud": 500000, "data_baud": 2000000},
    "twai":  {"baud": 500000}
  },
  "transmit": [                      // 发送列表，诊断/参数写入这类「快捷项」就在这儿
    {"name": "测试请求", "chn": 0, "id": "0x7E0", "fd": true, "brs": true,
     "data": "02 10 03 00 00 00 00 00", "period_ms": 0, "enabled": false},
    {"name": "唤醒帧", "chn": 0, "id": "0x123", "period_ms": 10, "enabled": true}
  ],
  "watch":  [{"message": "CSCBCMCore_BC_CANFD1_NMCanFrame", "signal": "NM_NodeID"}],
  "graph":  [{"message": "...", "signal": "VehSpdLgtChks8", "color": "#2e86de"}],
  "trace":  {"mode": "fixed", "filter_id": "", "autoscroll": true},
  "layout": {"active_tab": 0, "window_geometry": "1280x800+100+60"}
}
```

**与 `settings.json` 的分工**（不要混）：

| | 存什么 | 跟谁走 |
|---|---|---|
| `settings.json` | 主题、窗口几何、上次用的串口 | **程序偏好**，跟这台电脑走 |
| `*.bsp` 工程文件 | 数据库、发送列表、监控/波形、通道配置 | **工作内容**，跟项目走，可提交、可分发给同事 |

#### 交互

```
文件 -> 新建工程 / 打开工程 / 保存 / 另存为 / 最近打开
标题栏显示当前工程名与「已修改」星号
启动时自动加载上次工程（settings.json 记路径）
命令行： python -m BusSpyTool.app --project xxx.bsp
         python -m BusSpyTool.cli --project xxx.bsp send --name "测试请求"
```

CLI 也吃工程文件 —— 这样台架脚本可以直接 `send --name "测试请求"`，
不用在命令行里重复敲 ID 和数据。

#### 落点

```
core/project.py     Project 数据类 + load/save/migrate（version 字段留给格式升级）
ui/main_window.py   文件菜单、标题栏脏标记、启动自动加载
各 page            from_config() / to_config()，各自负责自己那段
```

> **路径要存相对路径**（相对于工程文件所在目录），否则把工程发给同事就全是断链。
> 绝对路径只在用户选的数据库不在工程目录树下时才退化使用。

#### 附：调试探针不属于本工具范围

调试探针与 SPI 外设承担不同职责，不能互相替代。本工具负责总线报文收发、
解析与记录，不提供任意地址读写、断点、单步或片上 trace 等芯片调试功能。

---

## 6. 以太网：ESP32 作被测网段上的独立节点

**定位要分清**，这是本方案最容易被误解的一点：

```
电脑(本工具) ──USB CDC──> ESP32 ──MCP2518FD──> CAN-FD 总线
                            ├────TWAI───────> CAN2.0B #1（预留）
                            ├─ CAN 控制器 ──> CAN2.0B #2/#3（预留）
                            ├─ MCP2518FD ──> CAN-FD #2（预留）
                            └────W5500──────> 被测以太网 ── ECU
                                              ↑ 本章讲的是这一段
```

- **USB 是管理链路**（跑 BSTP），**W5500 是被测总线**，两者互不干扰。
- ESP32 在被测网段上是一个**独立节点**，自己与被测 ECU 收发裸 UDP / SOME/IP 信号，
  **不依赖电脑转发**。
- 产品目标保留一个 W5500 专用于被测网络，不拿它接上位机；其 SPI 与多路 CAN 控制器的共享方案需在板级设计阶段验证。

**本期范围：裸 UDP 帧收发。SOME/IP 固件侧不做**（界面与流程先行，见 `ui/eth_page.py`）。

### 6.1 ARXML 能解出以太网通信矩阵（实测）

ARXML 中可提取以下以太网通信关系：

```
SOCKET-CONNECTION-BUNDLE            socket 连接束
SOCKET-ADDRESS                      IP + 端口
UDP-TP                              UDP 传输层
APPLICATION-ENDPOINT                应用端点
SOCKET-CONNECTION-IPDU-IDENTIFIER   PDU 在 socket 上的 header ID
ETHERNET-CLUSTER                    以太网网络
PROVIDED-SERVICE-INSTANCE           SOME/IP 提供服务（可选）
CONSUMED-SERVICE-INSTANCE           SOME/IP 消费服务（可选）
```

所以 UDP 报文的 IP / 端口 / header ID / 信号位布局**全都能解出来**。两个坑：

- **cantools 解不出这部分**（它的 ARXML 支持以 CAN/LIN 为主），需实现以太网描述解析器。
- **大型 ARXML 应使用 `iterparse` 流式解析**，避免 DOM 全量加载占用过多内存。

### 6.2 SOME/IP 实现边界（非本工具依赖）

```
frame     SOME/IP frame encode/decode and E2E counter
client    service discovery, subscription, request/response
server    service offer, event notification and subscription
```

SOME/IP 栈包含 SD、E2E、TCP/UDP 与多播；本工具当前不依赖或导入该实现。

### 6.3 为什么固件侧本期不做 SOME/IP

1. ESP32-S3 内存（512 KB SRAM + 8 MB PSRAM）与 W5500 吞吐（~10 Mbps）
   撑不住 SOME/IP 事件组的大流量通知。
2. 固件当前仍是 RGB 验证程序；先完成 CAN-FD 1 主干（P0–P2），以太网应用层后续实现。
3. SOME/IP 的价值在**协议栈行为的正确性测试**（构造畸形包、改 SD 时序、注入 E2E 错误），
   这些在 PC 上做更灵活；固件侧更适合做「稳定的仿真节点」而非「测试仪」。

### 6.4 本期范围：裸 UDP 帧收发

固件侧需要的东西很少：

- 一个额外 UDP socket（与 BSTP 控制口分开，端口由 `CFG_SET` 下发）
- 按配置表周期发送 / 按 header ID 过滤接收 ——
  **复用 4.3 节的周期引擎，不另写调度器**
- 收到的帧经 BSTP 的 `RX_FRAME` 通道上报（`chn = 2` 表示 ETH，见 `core/bstp.py` 的 `Chn`）

> 这样 CAN 帧与裸 UDP 帧**共用同一条上报链路和同一个时间基准**，
> 跨总线的时序比对（CAN 信号 → 以太网帧的端到端延迟）才有意义。
> 这是把以太网收发放进同一台设备、而不是让 PC 直连被测网的主要理由。

PDU 定义来源见 6.1（ARXML 的 `SOCKET-CONNECTION-IPDU-IDENTIFIER` 等）。
上位机侧界面已就位（`ui/eth_page.py`），控件置灰待固件。

### 6.5 若将来要做 SOME/IP（留档，本期不实施）

技术上完全可行，SOME/IP over UDP 只是 16 字节大端头：

```c
struct someip_hdr {            // 16 bytes, 全部大端
    uint16_t service_id, method_id;
    uint32_t length;              // 从 request_id 开始算
    uint16_t client_id, session_id;
    uint8_t  protocol_version;    // 0x01
    uint8_t  interface_version;
    uint8_t  message_type;        // 0x00 REQUEST, 0x80 RESPONSE, 0x02 NOTIFICATION
    uint8_t  return_code;
};
```

实施范围应限定为：`OfferService` / `FindService` 响应 / `Subscribe` + `SubscribeAck` / `Notify`。
SD 需要多播 `224.244.224.245:30490`（lwIP 的 IGMP 支持，W5500 可用）。
**明确不做**：vsomeip 级完整栈、TCP 传输、SOME/IP-TP 分段。

---

## 7. 里程碑与验收判据

### 已完成：上位机（H 阶段）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **H0** BSTP 协议层 | `core/bstp.py` | ✅ `tools/selftest.py` 全绿：编解码 / 批量切包 / DLC 映射 / 流式重同步 / 对齐 |
| **H1** 传输层 | USB CDC + UDP，`core/transport.py` | ✅ 字节流重同步实测：垃圾前缀、逐字节喂、假 magic、缓冲有界 |
| **H2** 设备会话 + 模拟器 | `core/device.py` / `core/mock.py` | ✅ 模拟器可按测试 DBC 产流量 |
| **H3** 数据库 | `core/database.py`（cantools） | ✅ 测试 DBC 报文与信号解析验证通过 |
| **H4** GUI | Trace / 波形 / 发送 / 信号 / 统计 / 以太网 / 日志 | ✅ Windows 300 帧/s、Linux 360 帧/s 实测流畅 |
| **H5** CLI | `cli.py` | ✅ 只 import core，无 X 机器可用 |

### 固件（P 阶段；主功能待做）

已建立一个独立的 RGB 常亮验证工程（`demo/fireware/`），默认控制板载 `RGB@IO48` WS2812；它不包含 BSTP、Wi-Fi 配网或总线功能。固件源码已加入固定 endpoint ID 和 CAN/Ethernet 驱动接口骨架，但尚无 CAN 控制器驱动。以下 P 阶段是产品固件工作，不包含 RGB 验证功能：

| 阶段 | 内容 | 验收判据 |
|---|---|---|
| **P0** 硬件打通 | SPI 通 MCP2518FD，回环自收自发 | 读 `CiCON` 符合预期；500k/2M 回环 1000 帧零丢 |
| **P1** CAN-FD + BSTP over USB | 2.2 节协议 + TinyUSB CDC | `BusSpyTool.cli monitor --usb` 能收到带 `ts_us` 的帧；批量包解析正确 |
| **P2** 周期引擎 + E2E | 4.3 / 4.5 节 | 10 ms 周期帧连跑 1 小时：**抖动 p99 < 500 µs，`cyc_miss` = 0，无时基漂移** |
| **P3** CAN2.0B #1（TWAI） | `BUSSPY_CH_CAN_CLASSIC_1` | 与 CAN-FD 1 同时收发 |
| **P4** W5500 + 裸 UDP 帧 | 6.4 节，复用周期引擎 | 与被测 ECU 对通，`chn=2` 的帧正确上报 |
| **P5** 其余 3 路 CAN 控制器 | CAN-FD 2、CAN2.0B #2/#3 的既有 ID 和接口 | 多通道并发压测，验证 USB/W5500 吞吐与丢帧 |
| **P6**（可选）SOME/IP 端点 | 6.5 节 | 通用抓包工具能识别 OfferService |

**分阶段硬件依赖：** USB CDC 是 S3 原生外设，不需要 W5500；P0–P2 可先用现有 ESP32-S3 和 MCP2518FD 开发板联调推进：

- P3 需要 CAN 收发器；P4 需要 W5500；P5 需要其余外部 CAN 控制器/收发器并依据 V1.4 图纸完成板级复核
- 上位机侧已能用模拟器验证协议与界面；固件端点 ID 不随硬件阶段重排

> **P2 的判据是单路 CAN-FD 主干的关键验收项** —— 如果周期抖动达不到，
> 这个工具就只剩「廉价 CAN 分析仪」，失去了「把调度下放固件」的全部意义。

---

## 8. 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| W5500 未到货 | **低** | 不阻塞 P0–P3；P4 才需要 W5500 |
| 最终 5 路 CAN + W5500 的 SPI/CPU/USB 吞吐不足 | 中 | 先做单路验收；P5 前按目标负载测算和实测，必要时更换主控/控制器架构 |
| W5500 SPI 与 CAN 控制器 SPI 争抢资源 | 中 | 具体分组未冻结；按 2025-V1.4 图纸审核，进行并发压力测试后再定板 |
| TBC 32 位 71.6 分钟回绕 | 中 | 固件做 64 位软扩展（3.7 节注） |
| **N16R8 的 Octal PSRAM 占用 GPIO 33–37** | 中 | 引脚分配避开，见 3.4。上电即失败的典型原因 |
| 保留的通道 ID 与 BSTP v1 兼容 | 中 | 固定 ID 0–2，新增通道只追加 ID；用自测保护历史映射 |
| **BSTP 两侧一致性需自己维护** | 中 | 自有协议没有现成参考实现。对策：结构体定义只写一份（C header），用脚本生成 Python ctypes，避免手抄漂移 |
| 热路径静默 catch 藏掉配置错误 | 低 | 已踩过：`database.decode` 用了 cantools 不存在的参数名，异常被吞，表现为「波形图全空」却无线索。现改为**首次失败必记一笔**（`core/database.py`） |
| 预生成类 807K 行，import 开销可能超过解码开销 | 低 | 仅记录，本期不改（5.3 节）。按需懒加载是后续方向 |
| MCP2518FD 模块晶振可能是 20 MHz | 低 | 采购核对丝印（3.6 节注） |

---

## 9. 代码位置索引

### 本工具（`BusSpyTool/`）

| 内容 | 路径 |
|---|---|
| BSTP 协议 | `core/bstp.py` |
| 传输层（USB CDC / UDP） | `core/transport.py` |
| 设备会话 | `core/device.py` |
| 模拟设备 | `core/mock.py` |
| DBC / ARXML 加载 | `core/database.py` |
| Trace 缓冲与聚合 | `core/tracebuf.py` |
| 主窗口 | `ui/main_window.py` |
| 波形图 | `ui/graph_page.py` |
| core 自测 / UI 冒烟 | `tools/selftest.py` / `tools/uitest.py` |

### 外部参考（不随仓库分发）

| 内容 | 路径 |
|---|---|
| CAN 总线参考实现 | 外部资料，不随仓库分发 |
| E2E Profile 测试向量 | 使用独立测试数据，不随仓库分发 |
| ARXML / DBC 测试库 | 使用者提供且有权使用的测试库，不随仓库分发 |

---

## 10. 决策记录与剩余待办

### 已定

| 决策点 | 选择 |
|---|---|
| **产品定位** | **独立仿 CANoe 工具，本期不接测试框架** |
| 上位机连接 | **USB CDC-ACM 为主**；Wi-Fi / 以太网为辅 |
| W5500 用途 | **专用于被测以太网**（接被测 ECU），不拿来接上位机 |
| UDP 协议 | **自有 BSTP v1**，带 magic / 版本 / 序列号 / 批量帧 |
| 数据库 | **运行时**加载 DBC / ARXML（cantools），非预生成类 |
| SOME/IP | 固件侧本期不做，先做裸 UDP 帧 |
| 固件开发 | **ESP-IDF；当前在 macOS 配置** |
| 上位机 | **Python + ttkbootstrap**，Windows / Linux 双平台实测通过 |
| 版本号 | **暂不启用**；启用后上位机与固件**分开管理** |
| 目标平台 | 无 FlexRay 的区域架构；含 FlexRay 的平台不在本期范围 |

### 剩余待核对（需实物 / 需实测）

1. **MCP2518FD 模块**：晶振是否 40 MHz？是否自带 CAN 收发器？—— 核对丝印。
2. **W5500 采购**：型号与到货时间（只影响 P4）。
3. **ESP32-S3 DevKit 的 USB 口**：是原生 USB（GPIO19/20）还是 UART 桥？
   原生口才能跑 TinyUSB CDC，VID 应为 `0x303A`。
4. **被测以太网的网段规划**：被测 ECU 侧 IP / 掩码，决定 W5500 怎么配。
5. **固件开工顺序**：建议 P0（SPI 回环）→ P1（USB CDC + BSTP）→ P2（周期引擎），
   前三步只用现有物料。
