# ESP32-S3 N16R8 GPIO scan diagnostic

This is a separate, temporary ESP-IDF firmware package. It does not modify or
replace the OLED/Wi-Fi/BLE demo in `demo/fireware`.

The project defaults enable 16 MB flash and 8-line Octal PSRAM at 80 MHz for an
ESP32-S3 N16R8 module. In VS Code, open this folder as the ESP-IDF project and
select the `esp32s3` target before building.

The diagnostic checks PSRAM initialization and its reported size, then toggles
only candidate GPIOs: 4, 5, 6, 9-18, 38-42, and 47. It skips strapping pins
(0, 3, 45, 46), native USB (19, 20), Octal memory pins (26-37), UART0 (43, 44),
and the pins assigned to OLED (7, 8) and RGB LED (48) in the main demo.

Disconnect external modules before running the test. Output readback confirms
the ESP32 pad's reported level only; it cannot detect every board-level
connection or prove a GPIO is safe for another circuit.

Use the ESP-IDF extension to build and flash only the application partition.
Do not erase flash or flash a new partition table for this diagnostic. To
restore the regular demo, reopen `demo/fireware` as the ESP-IDF project and
build/flash it using its documented procedure.
