#include <stdbool.h>
#include <stddef.h>

#include "esp_err.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "led_strip.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define RGB_LED_COUNT 1
#define RGB_LED_RMT_RESOLUTION_HZ (10 * 1000 * 1000)

static const char *TAG = "busspy_rgb";

void app_main(void)
{
    const led_strip_config_t strip_config = {
        .strip_gpio_num = CONFIG_RGB_LED_GPIO,
        .max_leds = RGB_LED_COUNT,
        .led_pixel_format = LED_PIXEL_FORMAT_GRB,
        .led_model = LED_MODEL_WS2812,
        .flags.invert_out = false,
    };
    const led_strip_rmt_config_t rmt_config = {
#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 0, 0)
        .rmt_channel = 0,
#else
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = RGB_LED_RMT_RESOLUTION_HZ,
        .flags.with_dma = false,
#endif
    };

    led_strip_handle_t strip = NULL;
    ESP_ERROR_CHECK(led_strip_new_rmt_device(
        &strip_config, &rmt_config, &strip));
    ESP_ERROR_CHECK(led_strip_clear(strip));
    ESP_ERROR_CHECK(led_strip_set_pixel(
        strip, 0, 0, CONFIG_RGB_LED_BRIGHTNESS, 0));
    ESP_ERROR_CHECK(led_strip_refresh(strip));

    ESP_LOGI(TAG, "Solid green WS2812 on GPIO %d at brightness %d",
             CONFIG_RGB_LED_GPIO, CONFIG_RGB_LED_BRIGHTNESS);

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
