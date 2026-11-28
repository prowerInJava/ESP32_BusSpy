#include <stddef.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_psram.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "gpio_scan";

static const gpio_num_t s_scan_pins[] = {
    GPIO_NUM_4,  GPIO_NUM_5,  GPIO_NUM_6,  GPIO_NUM_9,  GPIO_NUM_10,
    GPIO_NUM_11, GPIO_NUM_12, GPIO_NUM_13, GPIO_NUM_14, GPIO_NUM_15,
    GPIO_NUM_16, GPIO_NUM_17, GPIO_NUM_18, GPIO_NUM_38, GPIO_NUM_39,
    GPIO_NUM_40, GPIO_NUM_41, GPIO_NUM_42, GPIO_NUM_47,
};

static void check_psram(void)
{
    if (!esp_psram_is_initialized()) {
        ESP_LOGE(TAG, "Octal PSRAM did not initialize");
        return;
    }

    const size_t size = esp_psram_get_size();
    ESP_LOGI(TAG, "PSRAM initialized: %u MB",
             (unsigned)(size / (1024U * 1024U)));
    if (size != 8U * 1024U * 1024U) {
        ESP_LOGW(TAG, "Expected 8 MB; detected %u bytes", (unsigned)size);
    }
}

static void scan_pin(gpio_num_t pin)
{
    if (!GPIO_IS_VALID_GPIO(pin)) {
        ESP_LOGW(TAG, "GPIO%d is invalid; skipped", pin);
        return;
    }

    const gpio_config_t config = {
        .pin_bit_mask = 1ULL << pin,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "GPIO%d configuration failed: %s", pin,
                 esp_err_to_name(err));
        return;
    }

    err = gpio_set_level(pin, 1);
    if (err == ESP_OK) {
        vTaskDelay(pdMS_TO_TICKS(200));
        const int high_readback = gpio_get_level(pin);
        err = gpio_set_level(pin, 0);
        if (err == ESP_OK) {
            vTaskDelay(pdMS_TO_TICKS(200));
            const int low_readback = gpio_get_level(pin);
            ESP_LOGI(TAG, "GPIO%d output readback HIGH=%d LOW=%d", pin,
                     high_readback, low_readback);
        }
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "GPIO%d output test failed: %s", pin,
                 esp_err_to_name(err));
    }

    const esp_err_t reset_err = gpio_reset_pin(pin);
    if (reset_err != ESP_OK) {
        ESP_LOGW(TAG, "GPIO%d reset failed: %s", pin,
                 esp_err_to_name(reset_err));
    }
    vTaskDelay(pdMS_TO_TICKS(100));
}

void app_main(void)
{
    ESP_LOGI(TAG, "===== N16R8 OCTAL PSRAM CHECK =====");
    check_psram();

    ESP_LOGI(TAG, "===== SAFE GPIO OUTPUT READBACK TEST =====");
    ESP_LOGI(TAG,
             "Skipping GPIO 0/3/45/46 (strapping), 19/20 (USB), 26-37 "
             "(Octal memory), 7/8 (OLED), 43/44 (UART0), and 48 (RGB LED)");
    ESP_LOGW(TAG,
             "Disconnect external modules before testing. Output readback "
             "does not prove a pin is electrically unused.");

    for (size_t i = 0; i < sizeof(s_scan_pins) / sizeof(s_scan_pins[0]); i++) {
        scan_pin(s_scan_pins[i]);
    }

    ESP_LOGI(TAG, "===== GPIO TEST FINISHED =====");
    ESP_LOGI(TAG,
             "Candidate SPI pins: GPIO4/5/6 and GPIO9-18, 38-42, 47");
    while (true) {
        vTaskDelay(portMAX_DELAY);
    }
}
