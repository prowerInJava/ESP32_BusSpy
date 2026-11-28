# RGB 验证固件：编译与烧录手顺

本文针对 ESP32-S3 核心板和 `demo/fireware` 下的 RGB 常亮验证程序。该程序只点亮方形板载 WS2812，不包含 Wi-Fi 配网或 BusSpy 协议。

> **重要：** 烧录会覆盖当前运行的网页配网应用。原应用可以通过完整闪存备份恢复，但烧录前请先确认备份文件仍在且校验值正确。不要执行整片擦除或完整项目烧录。

## 1. 准备工具和连接

1. 在 VS Code 的 ESP-IDF 扩展中安装并选择 **ESP-IDF 5.4.2**。本工程尚未在资料包教程中的 ESP-IDF 4.4 下验证。
2. 当前 RGB 验证固件烧录/看日志时，连接板上标有 **USB** 的接口。macOS 上此原生 USB Serial/JTAG 串口通常显示为 `/dev/cu.usbmodem...`；不要选蓝牙串口，也不要把 USB 当成 U 盘使用。
3. 板上另一个标为 **UART** 的接口经 USB-UART 桥连接芯片串口，可用于串口烧录和 UART 日志。它与 USB 口用途不同，但当前这份烧录手顺统一使用 **USB** 口。
4. **USB OTG 什么时候用：**这份 RGB 固件不实现 USB OTG 应用功能，所以现在不需要为了它切换接口。后续固件启用原生 USB CDC（如 TinyUSB CDC-ACM）时，用原生 USB 口连接电脑，承载 BusSpy 与上位机之间的 BSTP 数据；若将设备配置为 USB Host，则用于连接兼容的 USB 外设。USB Serial/JTAG 是当前烧录/日志通道，不等同于应用层 USB CDC；它们共用原生 USB 引脚，应用 CDC 接管后不能同时依赖 USB Serial/JTAG，烧录和日志方式需按固件配置安排。
5. 确认原板全片备份存在：

   ```text
   ~/Downloads/ESP32-S3-original-flash-20261128-0041.bin
   SHA-256: 7c3a0c7d531e52eff65c22af9b09712efc46c289a6cac1184dde10b76f5db5e3
   ```

   可在终端校验：

   ```bash
   shasum -a 256 "$HOME/Downloads/ESP32-S3-original-flash-20261128-0041.bin"
   ```

   备份文件应位于仓库之外，不要提交到 Git。

## 2. 编译生成 BIN

在 VS Code 打开仓库后，使用 ESP-IDF 终端执行：

```bash
cd demo/fireware
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
```

`menuconfig` 中可以调整 LED GPIO 和亮度；默认 GPIO 48、亮度 12。首次构建需要联网下载 `espressif/led_strip` 组件。

构建成功后，应用镜像为：

```text
demo/fireware/build/busspy_rgb_constant.bin
```

如果在 `demo/fireware` 目录下继续执行后续命令，使用相对路径 `build/busspy_rgb_constant.bin`。

## 3. 确认分区和镜像大小

2026-11-28 从原板备份中解析到的分区布局：

| 分区 | 起始地址 | 大小 |
|---|---:|---:|
| NVS | `0x9000` | `0x5000` |
| OTA 数据 | `0xe000` | `0x2000` |
| `app0` | `0x10000` | `0x140000` |
| `app1` | `0x150000` | `0x140000` |

备份中的 OTA 序号为 1，按双 OTA 分区规则当时选择启动 `app0`。若从备份完成后没有更改过板上固件或 OTA 状态，烧录地址为 `0x10000`。**若设备状态可能已变化，先重新读取分区表及 OTA 数据，不要直接使用此地址。**

在 ESP-IDF 终端中检查应用镜像不超过 `app0` 的 `0x140000` 字节（1,310,720 字节）：

```bash
APP_BIN=build/busspy_rgb_constant.bin
test "$(stat -f %z "$APP_BIN")" -le 1310720 || {
    echo "应用镜像超过 app0 分区大小，停止烧录"
    exit 1
}
```

## 4. 只烧录 app0

1. 关闭 VS Code 串口监视器，避免它占用端口。
2. 确认串口名：

   ```bash
   ls /dev/cu.usbmodem*
   ```

3. 设置端口并仅写应用分区：

   ```bash
   PORT=/dev/cu.usbmodem5D4E2826381
   python -m esptool --chip esp32s3 --port "$PORT" write-flash \
       0x10000 "$APP_BIN"
   ```

   若当前设备端口不同，替换 `PORT` 值。保持 esptool 默认波特率；本板提高波特率读取时曾出现串口数据错误。

此命令只写 `app0`，不会写 OTA 数据、分区表或 NVS，但会覆盖 `app0` 中的网页配网固件。**不要使用 `idf.py flash`、`idf.py erase-flash` 或从 `0x0` 写入新应用。**

如果 esptool 无法自动进入下载模式，按住 BOOT、点按 RESET，再松开 BOOT 后重试。

## 5. 验证

烧录结束后按 RESET，或用 ESP-IDF 监视器查看启动日志：

```bash
idf.py -p "$PORT" monitor
```

成功启动时应看到类似 `Solid green WS2812 on GPIO 48 at brightness 12` 的日志；方形板载 RGB 灯以低亮度绿色常亮。旁边的电源及状态指示灯不是本 demo 控制的灯。

## 6. 恢复原固件

以下操作会覆盖整片闪存，包括新固件、分区表、OTA 数据及 NVS。只对**原来的同一块板**执行，且先确认 SHA-256、端口和备份文件：

```bash
PORT=/dev/cu.usbmodem5D4E2826381
python -m esptool --chip esp32s3 --port "$PORT" write-flash 0x0 \
    "$HOME/Downloads/ESP32-S3-original-flash-20261128-0041.bin"
```

如果 esptool 的串口读取/写入出现数据校验错误，不要把失败当成成功；先检查串口监视器是否关闭、USB 数据线和连接，再用默认波特率重试。
