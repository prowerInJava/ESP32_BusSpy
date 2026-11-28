idf_component_register(
    SRCS "wifi_portal.c" "main.c" "busspy_interfaces.c"
    INCLUDE_DIRS "."
    REQUIRES bt esp_driver_i2c esp_event esp_http_server esp_netif esp_wifi
            led_strip nvs_flash freertos esp_common
)
