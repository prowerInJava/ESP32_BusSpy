#include "busspy_interfaces.h"

_Static_assert(BUSSPY_CH_CANFD_1 == 0, "BSTP v1 CAN-FD channel ID changed");
_Static_assert(BUSSPY_CH_CAN_CLASSIC_1 == 1, "BSTP v1 TWAI channel ID changed");
_Static_assert(BUSSPY_CH_ETHERNET == 2, "BSTP v1 Ethernet channel ID changed");
_Static_assert(BUSSPY_CH_CANFD_2 == 3, "CAN-FD 2 channel ID changed");
_Static_assert(BUSSPY_CH_CAN_CLASSIC_2 == 4, "CAN 2 channel ID changed");
_Static_assert(BUSSPY_CH_CAN_CLASSIC_3 == 5, "CAN 3 channel ID changed");
_Static_assert(BUSSPY_CH_COUNT == 6, "BSTP endpoint count changed");

static const busspy_channel_info_t s_channels[BUSSPY_CH_COUNT] = {
    [BUSSPY_CH_CANFD_1] = {
        .id = BUSSPY_CH_CANFD_1,
        .name = "CAN-FD 1",
        .kind = BUSSPY_ENDPOINT_CAN,
        .mode = BUSSPY_CAN_FD,
        .phase = BUSSPY_CHANNEL_PHASE_1,
    },
    [BUSSPY_CH_CAN_CLASSIC_1] = {
        .id = BUSSPY_CH_CAN_CLASSIC_1,
        .name = "CAN 2.0B 1 (TWAI)",
        .kind = BUSSPY_ENDPOINT_CAN,
        .mode = BUSSPY_CAN_CLASSIC,
        .phase = BUSSPY_CHANNEL_RESERVED,
    },
    [BUSSPY_CH_ETHERNET] = {
        .id = BUSSPY_CH_ETHERNET,
        .name = "Ethernet (W5500)",
        .kind = BUSSPY_ENDPOINT_ETHERNET,
        .mode = BUSSPY_CAN_MODE_NONE,
        .phase = BUSSPY_CHANNEL_RESERVED,
    },
    [BUSSPY_CH_CANFD_2] = {
        .id = BUSSPY_CH_CANFD_2,
        .name = "CAN-FD 2",
        .kind = BUSSPY_ENDPOINT_CAN,
        .mode = BUSSPY_CAN_FD,
        .phase = BUSSPY_CHANNEL_RESERVED,
    },
    [BUSSPY_CH_CAN_CLASSIC_2] = {
        .id = BUSSPY_CH_CAN_CLASSIC_2,
        .name = "CAN 2.0B 2",
        .kind = BUSSPY_ENDPOINT_CAN,
        .mode = BUSSPY_CAN_CLASSIC,
        .phase = BUSSPY_CHANNEL_RESERVED,
    },
    [BUSSPY_CH_CAN_CLASSIC_3] = {
        .id = BUSSPY_CH_CAN_CLASSIC_3,
        .name = "CAN 2.0B 3",
        .kind = BUSSPY_ENDPOINT_CAN,
        .mode = BUSSPY_CAN_CLASSIC,
        .phase = BUSSPY_CHANNEL_RESERVED,
    },
};

const busspy_channel_info_t *busspy_channel_get_info(busspy_channel_id_t id)
{
    if ((unsigned)id >= BUSSPY_CH_COUNT) {
        return NULL;
    }
    return &s_channels[id];
}
