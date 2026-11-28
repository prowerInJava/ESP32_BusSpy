#ifndef BUSSPY_INTERFACES_H
#define BUSSPY_INTERFACES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"

#define BUSSPY_CAN_FRAME_MAX_DATA 64U

/* BSTP v1 endpoint IDs. Keep 0-2 stable; append new endpoints only. */
typedef enum {
    BUSSPY_CH_CANFD_1 = 0,
    BUSSPY_CH_CAN_CLASSIC_1 = 1,
    BUSSPY_CH_ETHERNET = 2,
    BUSSPY_CH_CANFD_2 = 3,
    BUSSPY_CH_CAN_CLASSIC_2 = 4,
    BUSSPY_CH_CAN_CLASSIC_3 = 5,
    BUSSPY_CH_COUNT = 6
} busspy_channel_id_t;

typedef enum {
    BUSSPY_CHANNEL_PHASE_1 = 0,
    BUSSPY_CHANNEL_RESERVED = 1
} busspy_channel_phase_t;

typedef enum {
    BUSSPY_CAN_MODE_NONE = 0,
    BUSSPY_CAN_CLASSIC = 1,
    BUSSPY_CAN_FD = 2
} busspy_can_mode_t;

typedef enum {
    BUSSPY_ENDPOINT_CAN = 0,
    BUSSPY_ENDPOINT_ETHERNET = 1
} busspy_endpoint_kind_t;

typedef struct {
    uint32_t can_id;
    uint64_t timestamp_us;
    uint8_t data[BUSSPY_CAN_FRAME_MAX_DATA];
    uint8_t data_len;
    bool extended_id;
    bool fd;
    bool brs;
    bool esi;
    bool remote_request;
    bool error_frame;
} busspy_can_frame_t;

typedef struct {
    uint32_t nominal_bitrate;
    uint32_t data_bitrate;
    busspy_can_mode_t mode;
    bool enable_brs;
} busspy_can_config_t;

typedef struct {
    uint32_t rx_frames;
    uint32_t tx_frames;
    uint32_t rx_dropped;
    uint32_t tx_errors;
    uint16_t tx_error_count;
    uint16_t rx_error_count;
    uint8_t error_state;
    bool bus_off;
} busspy_can_status_t;

typedef struct {
    esp_err_t (*configure)(void *context, const busspy_can_config_t *config);
    esp_err_t (*start)(void *context);
    esp_err_t (*stop)(void *context);
    esp_err_t (*transmit)(void *context, const busspy_can_frame_t *frame);
    esp_err_t (*receive)(void *context, busspy_can_frame_t *frame,
                         TickType_t timeout_ticks);
    esp_err_t (*get_status)(void *context, busspy_can_status_t *status);
} busspy_can_driver_ops_t;

typedef struct {
    busspy_channel_id_t id;
    const char *name;
    busspy_endpoint_kind_t kind;
    busspy_can_mode_t mode;
    busspy_channel_phase_t phase;
} busspy_channel_info_t;

/*
 * Ethernet is a packet-network interface, not a CAN controller. Keep it
 * separate from the CAN driver API so W5500 can be added without changing
 * CAN channel contracts.
 */
typedef struct {
    esp_err_t (*start)(void *context);
    esp_err_t (*send_udp)(void *context, uint32_t destination_ipv4,
                          uint16_t destination_port, const uint8_t *data,
                          size_t data_len);
    esp_err_t (*receive_udp)(void *context, uint8_t *buffer, size_t capacity,
                             size_t *received_len, uint32_t *source_ipv4,
                             uint16_t *source_port, TickType_t timeout_ticks);
    esp_err_t (*get_link_state)(void *context, bool *link_up);
} busspy_ethernet_driver_ops_t;

const busspy_channel_info_t *busspy_channel_get_info(busspy_channel_id_t id);

#endif
