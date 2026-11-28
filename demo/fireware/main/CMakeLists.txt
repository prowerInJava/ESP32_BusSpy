idf_component_register(
    SRCS "main.c" "busspy_interfaces.c"
    INCLUDE_DIRS "."
    REQUIRES led_strip freertos esp_common
)
