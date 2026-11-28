#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "driver/i2c_master.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_log.h"
#include "led_strip.h"

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include "host/ble_gap.h"
#include "host/ble_hs.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "wifi_portal.h"

#define OLED_SDA_GPIO 7
#define OLED_SCL_GPIO 8
#define OLED_WIDTH 128
#define OLED_HEIGHT 64
#define OLED_I2C_ADDRESS_1 0x3C
#define OLED_I2C_ADDRESS_2 0x3D
#define OLED_I2C_FREQUENCY_HZ 400000

#define BLE_DEVICE_NAME "BusSpy-S3"

#define STATUS_BLE_CONNECTED WIFI_PORTAL_BLE_CONNECTED_BIT

#define RGB_LED_COUNT 1
#define RGB_LED_RMT_RESOLUTION_HZ (10 * 1000 * 1000)

static const char *TAG = "busspy_demo";
static i2c_master_dev_handle_t s_oled;
static uint8_t s_framebuffer[OLED_WIDTH * OLED_HEIGHT / 8];
static EventGroupHandle_t s_status_events;
static led_strip_handle_t s_led_strip;
static TaskHandle_t s_led_task;
static portMUX_TYPE s_led_state_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_led_enabled = true;
static uint32_t s_led_step_ms = 1000;

static void ble_start_advertising(void);

static const uint8_t *font_glyph(char character)
{
    static const uint8_t glyphs[][5] = {
        {0x7e, 0x11, 0x11, 0x11, 0x7e}, /* A */
        {0x7f, 0x49, 0x49, 0x49, 0x36}, /* B */
        {0x3e, 0x41, 0x41, 0x41, 0x22}, /* C */
        {0x7f, 0x41, 0x41, 0x22, 0x1c}, /* D */
        {0x7f, 0x49, 0x49, 0x49, 0x41}, /* E */
        {0x7f, 0x09, 0x09, 0x09, 0x01}, /* F */
        {0x3e, 0x41, 0x49, 0x49, 0x7a}, /* G */
        {0x7f, 0x08, 0x08, 0x08, 0x7f}, /* H */
        {0x00, 0x41, 0x7f, 0x41, 0x00}, /* I */
        {0x20, 0x40, 0x41, 0x3f, 0x01}, /* J */
        {0x7f, 0x08, 0x14, 0x22, 0x41}, /* K */
        {0x7f, 0x40, 0x40, 0x40, 0x40}, /* L */
        {0x7f, 0x02, 0x0c, 0x02, 0x7f}, /* M */
        {0x7f, 0x04, 0x08, 0x10, 0x7f}, /* N */
        {0x3e, 0x41, 0x41, 0x41, 0x3e}, /* O */
        {0x7f, 0x09, 0x09, 0x09, 0x06}, /* P */
        {0x3e, 0x41, 0x51, 0x21, 0x5e}, /* Q */
        {0x7f, 0x09, 0x19, 0x29, 0x46}, /* R */
        {0x46, 0x49, 0x49, 0x49, 0x31}, /* S */
        {0x01, 0x01, 0x7f, 0x01, 0x01}, /* T */
        {0x3f, 0x40, 0x40, 0x40, 0x3f}, /* U */
        {0x1f, 0x20, 0x40, 0x20, 0x1f}, /* V */
        {0x3f, 0x40, 0x38, 0x40, 0x3f}, /* W */
        {0x63, 0x14, 0x08, 0x14, 0x63}, /* X */
        {0x07, 0x08, 0x70, 0x08, 0x07}, /* Y */
        {0x61, 0x51, 0x49, 0x45, 0x43}, /* Z */
    };

    static const uint8_t digits[][5] = {
        {0x3e, 0x45, 0x49, 0x51, 0x3e}, /* 0 */
        {0x00, 0x21, 0x7f, 0x01, 0x00}, /* 1 */
        {0x23, 0x45, 0x49, 0x51, 0x21}, /* 2 */
        {0x22, 0x41, 0x49, 0x49, 0x36}, /* 3 */
        {0x0c, 0x14, 0x24, 0x7f, 0x04}, /* 4 */
        {0x72, 0x51, 0x51, 0x51, 0x4e}, /* 5 */
        {0x1e, 0x29, 0x49, 0x49, 0x06}, /* 6 */
        {0x40, 0x47, 0x48, 0x50, 0x60}, /* 7 */
        {0x36, 0x49, 0x49, 0x49, 0x36}, /* 8 */
        {0x30, 0x49, 0x49, 0x4a, 0x3c}, /* 9 */
    };
    static const uint8_t lowercase[][5] = {
        {0x20, 0x54, 0x54, 0x54, 0x78}, /* a */
        {0x7f, 0x48, 0x44, 0x44, 0x38}, /* b */
        {0x38, 0x44, 0x44, 0x44, 0x20}, /* c */
        {0x38, 0x44, 0x44, 0x48, 0x7f}, /* d */
        {0x38, 0x54, 0x54, 0x54, 0x18}, /* e */
        {0x08, 0x7e, 0x09, 0x01, 0x02}, /* f */
        {0x0c, 0x52, 0x52, 0x52, 0x3e}, /* g */
        {0x7f, 0x08, 0x04, 0x04, 0x78}, /* h */
        {0x00, 0x44, 0x7d, 0x40, 0x00}, /* i */
        {0x20, 0x40, 0x44, 0x3d, 0x00}, /* j */
        {0x7f, 0x10, 0x28, 0x44, 0x00}, /* k */
        {0x00, 0x41, 0x7f, 0x40, 0x00}, /* l */
        {0x7c, 0x04, 0x18, 0x04, 0x78}, /* m */
        {0x7c, 0x08, 0x04, 0x04, 0x78}, /* n */
        {0x38, 0x44, 0x44, 0x44, 0x38}, /* o */
        {0x7c, 0x14, 0x14, 0x14, 0x08}, /* p */
        {0x08, 0x14, 0x14, 0x18, 0x7c}, /* q */
        {0x7c, 0x08, 0x04, 0x04, 0x08}, /* r */
        {0x48, 0x54, 0x54, 0x54, 0x20}, /* s */
        {0x04, 0x3f, 0x44, 0x40, 0x20}, /* t */
        {0x3c, 0x40, 0x40, 0x20, 0x7c}, /* u */
        {0x1c, 0x20, 0x40, 0x20, 0x1c}, /* v */
        {0x3c, 0x40, 0x30, 0x40, 0x3c}, /* w */
        {0x44, 0x28, 0x10, 0x28, 0x44}, /* x */
        {0x0c, 0x50, 0x50, 0x50, 0x3c}, /* y */
        {0x44, 0x64, 0x54, 0x4c, 0x44}, /* z */
    };
    static const uint8_t colon[5] = {0x00, 0x36, 0x36, 0x00, 0x00};
    static const uint8_t dash[5] = {0x08, 0x08, 0x08, 0x08, 0x08};
    static const uint8_t dot[5] = {0x00, 0x60, 0x60, 0x00, 0x00};

    if (character >= 'a' && character <= 'z') {
        return lowercase[character - 'a'];
    }
    if (character >= 'A' && character <= 'Z') {
        return glyphs[character - 'A'];
    }
    if (character >= '0' && character <= '9') {
        return digits[character - '0'];
    }
    switch (character) {
    case ':':
        return colon;
    case '-':
        return dash;
    case '.':
        return dot;
    default:
        return NULL;
    }
}

static void oled_set_pixel(int x, int y)
{
    if (x >= 0 && x < OLED_WIDTH && y >= 0 && y < OLED_HEIGHT) {
        s_framebuffer[(y / 8) * OLED_WIDTH + x] |= (uint8_t)(1U << (y % 8));
    }
}

static void oled_draw_line(int x0, int y0, int x1, int y1)
{
    const int dx = (x1 > x0) ? (x1 - x0) : (x0 - x1);
    const int sx = (x0 < x1) ? 1 : -1;
    const int dy = (y1 > y0) ? (y0 - y1) : (y1 - y0);
    const int sy = (y0 < y1) ? 1 : -1;
    int error = dx + dy;

    while (true) {
        oled_set_pixel(x0, y0);
        if (x0 == x1 && y0 == y1) {
            break;
        }
        const int doubled_error = 2 * error;
        if (doubled_error >= dy) {
            error += dy;
            x0 += sx;
        }
        if (doubled_error <= dx) {
            error += dx;
            y0 += sy;
        }
    }
}

static void oled_draw_char(char character, int x, int y)
{
    const uint8_t *glyph = font_glyph(character);
    if (glyph == NULL) {
        return;
    }
    for (int column = 0; column < 5; column++) {
        for (int row = 0; row < 7; row++) {
            if ((glyph[column] & (1U << row)) != 0) {
                oled_set_pixel(x + column, y + row);
            }
        }
    }
}

static void oled_draw_text(const char *text, int x, int y)
{
    while (*text != '\0') {
        oled_draw_char(*text, x, y);
        x += 6;
        text++;
    }
}

static void oled_draw_loading_glyph(unsigned int glyph, int x, int y)
{
    switch (glyph) {
    case 0: /* 正 */
        oled_draw_line(x + 2, y + 2, x + 14, y + 2);
        oled_draw_line(x + 8, y + 1, x + 8, y + 14);
        oled_draw_line(x + 4, y + 7, x + 13, y + 7);
        oled_draw_line(x + 3, y + 7, x + 3, y + 14);
        oled_draw_line(x + 2, y + 14, x + 14, y + 14);
        break;
    case 1: /* 在 */
        oled_draw_line(x + 3, y + 2, x + 6, y + 5);
        oled_draw_line(x + 5, y + 4, x + 5, y + 14);
        oled_draw_line(x + 6, y + 4, x + 14, y + 4);
        oled_draw_line(x + 7, y + 8, x + 14, y + 8);
        oled_draw_line(x + 11, y + 5, x + 11, y + 14);
        oled_draw_line(x + 7, y + 14, x + 14, y + 14);
        break;
    case 2: /* 加 */
        oled_draw_line(x + 2, y + 4, x + 8, y + 4);
        oled_draw_line(x + 7, y + 3, x + 7, y + 10);
        oled_draw_line(x + 7, y + 10, x + 3, y + 14);
        oled_draw_line(x + 9, y + 3, x + 15, y + 3);
        oled_draw_line(x + 9, y + 3, x + 9, y + 14);
        oled_draw_line(x + 15, y + 3, x + 15, y + 14);
        oled_draw_line(x + 9, y + 14, x + 15, y + 14);
        break;
    case 3: /* 载 */
        oled_draw_line(x + 2, y + 3, x + 14, y + 3);
        oled_draw_line(x + 8, y + 1, x + 8, y + 7);
        oled_draw_line(x + 4, y + 7, x + 13, y + 7);
        oled_draw_line(x + 4, y + 7, x + 4, y + 13);
        oled_draw_line(x + 4, y + 10, x + 13, y + 10);
        oled_draw_line(x + 8, y + 7, x + 8, y + 14);
        oled_draw_line(x + 13, y + 7, x + 13, y + 13);
        oled_draw_line(x + 3, y + 13, x + 14, y + 13);
        oled_draw_line(x + 11, y + 10, x + 15, y + 15);
        break;
    default: /* 中 */
        oled_draw_line(x + 3, y + 2, x + 13, y + 2);
        oled_draw_line(x + 3, y + 2, x + 3, y + 14);
        oled_draw_line(x + 13, y + 2, x + 13, y + 14);
        oled_draw_line(x + 3, y + 14, x + 13, y + 14);
        oled_draw_line(x + 8, y + 1, x + 8, y + 15);
        break;
    }
}

static esp_err_t oled_send_command(uint8_t command)
{
    const uint8_t packet[] = {0x00, command};
    return i2c_master_transmit(s_oled, packet, sizeof(packet), -1);
}

static esp_err_t oled_flush(void)
{
    uint8_t packet[OLED_WIDTH + 1];
    packet[0] = 0x40;

    for (uint8_t page = 0; page < OLED_HEIGHT / 8; page++) {
        esp_err_t err = oled_send_command((uint8_t)(0xB0 | page));
        if (err != ESP_OK) {
            return err;
        }
        if ((err = oled_send_command(0x00)) != ESP_OK ||
            (err = oled_send_command(0x10)) != ESP_OK) {
            return err;
        }
        memcpy(&packet[1], &s_framebuffer[page * OLED_WIDTH], OLED_WIDTH);
        err = i2c_master_transmit(s_oled, packet, sizeof(packet), -1);
        if (err != ESP_OK) {
            return err;
        }
    }
    return ESP_OK;
}

static esp_err_t oled_init(void)
{
    const i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = OLED_SDA_GPIO,
        .scl_io_num = OLED_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_config, &bus), TAG,
                        "Could not initialize OLED I2C bus");

    uint8_t address = 0;
    if (i2c_master_probe(bus, OLED_I2C_ADDRESS_1, 100) == ESP_OK) {
        address = OLED_I2C_ADDRESS_1;
    } else if (i2c_master_probe(bus, OLED_I2C_ADDRESS_2, 100) == ESP_OK) {
        address = OLED_I2C_ADDRESS_2;
    } else {
        ESP_LOGE(TAG, "No OLED found at I2C address 0x3C or 0x3D");
        return ESP_ERR_NOT_FOUND;
    }

    const i2c_device_config_t device_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = address,
        .scl_speed_hz = OLED_I2C_FREQUENCY_HZ,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &device_config, &s_oled),
                        TAG, "Could not add OLED to I2C bus");

    static const uint8_t init_commands[] = {
        0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14,
        0x20, 0x02, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0x7F, 0xD9, 0xF1,
        0xDB, 0x40, 0xA4, 0xA6, 0x2E, 0xAF,
    };
    for (size_t i = 0; i < sizeof(init_commands); i++) {
        ESP_RETURN_ON_ERROR(oled_send_command(init_commands[i]), TAG,
                            "OLED initialization command failed");
    }
    ESP_LOGI(TAG, "OLED detected at I2C address 0x%02X", address);
    return ESP_OK;
}

static void oled_show_loading(void)
{
    memset(s_framebuffer, 0, sizeof(s_framebuffer));
    const char *loading = "LOADING...";
    oled_draw_text(loading, 34, 3);
    for (unsigned int i = 0; i < 5; i++) {
        oled_draw_loading_glyph(i, 22 + (int)i * 17, 22);
    }
    oled_draw_text("PLEASE WAIT", 31, 49);
    ESP_ERROR_CHECK(oled_flush());
}

static void oled_show_status(void)
{
    const EventBits_t status = xEventGroupGetBits(s_status_events);
    const bool wifi_connected =
        (status & (WIFI_PORTAL_AP_CLIENT_BIT |
                   WIFI_PORTAL_STA_CONNECTED_BIT)) != 0;
    memset(s_framebuffer, 0, sizeof(s_framebuffer));
    oled_draw_text("HelloWorld", 34, 4);
    oled_draw_text(wifi_connected ? "WIFI: ONLINE" : "WIFI: OFFLINE",
                   22, 28);
    oled_draw_text((status & STATUS_BLE_CONNECTED) ? "BT: ONLINE"
                                                    : "BT: OFFLINE",
                   31, 46);
    ESP_ERROR_CHECK(oled_flush());
}

static int ble_gap_event_handler(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            ESP_LOGI(TAG, "Bluetooth LE client connected");
            xEventGroupSetBits(s_status_events, STATUS_BLE_CONNECTED);
        } else {
            ESP_LOGW(TAG, "Bluetooth LE connection failed; restarting advertising");
            ble_start_advertising();
        }
        return 0;
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "Bluetooth LE client disconnected");
        xEventGroupClearBits(s_status_events, STATUS_BLE_CONNECTED);
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        ESP_LOGI(TAG, "Bluetooth LE advertising ended; restarting");
        break;
    default:
        return 0;
    }

    ble_start_advertising();
    return 0;
}

static void ble_start_advertising(void)
{
    uint8_t address_type;
    const int address_result = ble_hs_id_infer_auto(0, &address_type);
    if (address_result != 0) {
        ESP_LOGE(TAG, "Could not determine Bluetooth LE address (%d)",
                 address_result);
        return;
    }

    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (const uint8_t *)BLE_DEVICE_NAME;
    fields.name_len = strlen(BLE_DEVICE_NAME);
    fields.name_is_complete = 1;
    const int fields_result = ble_gap_adv_set_fields(&fields);
    if (fields_result != 0) {
        ESP_LOGE(TAG, "Could not set Bluetooth LE advertising data (%d)",
                 fields_result);
        return;
    }

    const struct ble_gap_adv_params parameters = {
        .conn_mode = BLE_GAP_CONN_MODE_UND,
        .disc_mode = BLE_GAP_DISC_MODE_GEN,
    };
    const int result = ble_gap_adv_start(address_type, NULL, BLE_HS_FOREVER,
                                         &parameters, ble_gap_event_handler,
                                         NULL);
    if (result != 0) {
        ESP_LOGE(TAG, "Could not start Bluetooth LE advertising (%d)", result);
        return;
    }
    ESP_LOGI(TAG, "Bluetooth LE device '%s' is connectable without pairing",
             BLE_DEVICE_NAME);
}

static void ble_on_sync(void)
{
    ble_start_advertising();
}

static void ble_host_task(void *arg)
{
    (void)arg;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static void ble_start(void)
{
    ESP_ERROR_CHECK(nimble_port_init());
    ble_svc_gap_init();
    ble_svc_gatt_init();
    const int name_result = ble_svc_gap_device_name_set(BLE_DEVICE_NAME);
    ESP_ERROR_CHECK(name_result == 0 ? ESP_OK : ESP_FAIL);
    ble_hs_cfg.sync_cb = ble_on_sync;
    nimble_port_freertos_init(ble_host_task);
}

static void rgb_led_set(bool enabled, uint32_t step_ms)
{
    portENTER_CRITICAL(&s_led_state_lock);
    s_led_enabled = enabled;
    s_led_step_ms = step_ms;
    portEXIT_CRITICAL(&s_led_state_lock);
    if (s_led_task != NULL) {
        xTaskNotifyGive(s_led_task);
    }
}

static void rgb_led_get(bool *enabled, uint32_t *step_ms)
{
    portENTER_CRITICAL(&s_led_state_lock);
    *enabled = s_led_enabled;
    *step_ms = s_led_step_ms;
    portEXIT_CRITICAL(&s_led_state_lock);
}

static void rgb_led_apply(bool on)
{
    if (on) {
        ESP_ERROR_CHECK(led_strip_set_pixel(
            s_led_strip, 0, 0, CONFIG_RGB_LED_BRIGHTNESS, 0));
    } else {
        ESP_ERROR_CHECK(led_strip_clear(s_led_strip));
    }
    ESP_ERROR_CHECK(led_strip_refresh(s_led_strip));
}

static void rgb_led_task(void *arg)
{
    (void)arg;
    bool lit = true;
    while (true) {
        bool enabled;
        uint32_t step_ms;
        rgb_led_get(&enabled, &step_ms);
        if (!enabled) {
            rgb_led_apply(false);
            ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
            lit = true;
            continue;
        }
        rgb_led_apply(lit);
        lit = !lit;
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(step_ms));
    }
}

static void rgb_led_start(void)
{
    const led_strip_config_t strip_config = {
        .strip_gpio_num = CONFIG_RGB_LED_GPIO,
        .max_leds = RGB_LED_COUNT,
        .led_pixel_format = LED_PIXEL_FORMAT_GRB,
        .led_model = LED_MODEL_WS2812,
        .flags.invert_out = false,
    };
    const led_strip_rmt_config_t rmt_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = RGB_LED_RMT_RESOLUTION_HZ,
        .flags.with_dma = false,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(
        &strip_config, &rmt_config, &s_led_strip));
    ESP_ERROR_CHECK(xTaskCreate(rgb_led_task, "rgb_led", 2048, NULL, 5,
                                &s_led_task) == pdPASS
                        ? ESP_OK
                        : ESP_ERR_NO_MEM);
}

void app_main(void)
{
    s_status_events = xEventGroupCreate();
    ESP_ERROR_CHECK(s_status_events == NULL ? ESP_ERR_NO_MEM : ESP_OK);

    ESP_ERROR_CHECK(oled_init());
    oled_show_loading();
    const TickType_t loading_started = xTaskGetTickCount();
    rgb_led_start();

    ESP_ERROR_CHECK(wifi_portal_start(s_status_events, rgb_led_set,
                                      rgb_led_get));
    ble_start();

    const TickType_t loading_duration = pdMS_TO_TICKS(3000);
    const TickType_t loading_elapsed = xTaskGetTickCount() - loading_started;
    if (loading_elapsed < loading_duration) {
        vTaskDelay(loading_duration - loading_elapsed);
    }

    EventBits_t last_status = ~(EventBits_t)0;
    while (true) {
        const EventBits_t status = xEventGroupGetBits(s_status_events);
        if (status != last_status) {
            oled_show_status();
            last_status = status;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
