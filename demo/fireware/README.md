# OLED / Wi-Fi / Bluetooth demo

This ESP-IDF firmware targets the ESP32-S3 board and the 0.96-inch, 128x64
I2C OLED wired as shown in [the wiring guide](../../docs/OLED接线说明.md):

- SDA: GPIO 7
- SCL: GPIO 8
- OLED I2C address: auto-detected at `0x3C` or `0x3D`

After reset, the OLED shows `正在加载中` while the Wi-Fi portal and Bluetooth
Low Energy peripheral start. Three seconds later it shows `HelloWorld`,
`WiFi: ONLINE/OFFLINE`, and `BT: ONLINE/OFFLINE`. Wi-Fi is ONLINE when a phone
or computer joins the setup hotspot or the station connects to a router; BT
is ONLINE while a BLE client is connected. The ESP32-S3 supports BLE, not
Bluetooth Classic.

The firmware provides a WPA2-protected `BusSpy-S3` setup hotspot and the
original page at **http://192.168.4.1/**. Use ESP-IDF `menuconfig` → **BusSpy
OLED demo** → **Wi-Fi setup hotspot password** to set an 8–63 character
passphrase before building. The page shows device status, scans for routers,
saves router credentials, controls the onboard green LED, and can restart the
device. Saved router credentials are stored in NVS; the firmware does not
erase NVS or the full flash. NVS encryption/flash encryption is not enabled in
this demo, so do not treat stored router credentials as protected at rest.

The BLE peripheral `BusSpy-S3` remains connectable without pairing and exposes
only the standard GAP/GATT services. Nearby BLE clients can connect, but there
is no BusSpy data/control service. Recommended toolchain: ESP-IDF 5.4.2. Build
and flash guidance is in [BUILD_FLASH.md](./BUILD_FLASH.md).
