#ifndef WIFI_PORTAL_H
#define WIFI_PORTAL_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "freertos/event_groups.h"

#define WIFI_PORTAL_AP_CLIENT_BIT (1U << 0)
#define WIFI_PORTAL_STA_CONNECTED_BIT (1U << 1)
#define WIFI_PORTAL_BLE_CONNECTED_BIT (1U << 2)

typedef void (*wifi_portal_led_set_fn)(bool enabled, uint32_t step_ms);
typedef void (*wifi_portal_led_get_fn)(bool *enabled, uint32_t *step_ms);

esp_err_t wifi_portal_start(EventGroupHandle_t status_events,
                            wifi_portal_led_set_fn led_set,
                            wifi_portal_led_get_fn led_get);

#endif
