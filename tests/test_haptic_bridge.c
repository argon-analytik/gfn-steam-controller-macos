#include "../haptic_bridge.h"

#include <assert.h>
#include <stdint.h>
#include <string.h>

int main(void) {
    // Only Steam Controller 2 vendor collections can receive rumble writes.
    assert(gfn_is_supported_triton_output(0x28de, 0x1304, true, "USB"));
    assert(gfn_is_supported_triton_output(0x28de, 0x1303, true, "Bluetooth"));
    assert(gfn_is_supported_triton_output(
        0x28de, 0x1303, true, "Bluetooth Low Energy"));
    assert(!gfn_is_supported_triton_output(0x28de, 0x1303, false, "Bluetooth"));
    assert(!gfn_is_supported_triton_output(0x28de, 0x1304, false, "USB"));
    assert(!gfn_is_supported_triton_output(0x045e, 0x028e, true, "USB"));
    assert(!gfn_is_supported_triton_output(0x28de, 0x1102, true, "USB"));
    assert(!gfn_is_supported_triton_output(0x28de, 0x1303, true, "USB"));
    assert(!gfn_is_supported_triton_output(0x28de, 0x1304, true, "Bluetooth"));
    assert(!gfn_is_supported_triton_output(0x28de, 0x1303, true, NULL));
    assert(!gfn_is_supported_triton_output(0x28de, 0x1303, true, ""));
    assert(!gfn_is_supported_output_device(NULL));

    assert(gfn_map_rumble_level(-1) == 0);
    assert(gfn_map_rumble_level(0) == 0);
    assert(gfn_map_rumble_level(1) == 257);
    assert(gfn_map_rumble_level(30) == 7710);
    assert(gfn_map_rumble_level(128) == 32896);
    assert(gfn_map_rumble_level(255) == UINT16_MAX);
    assert(gfn_map_rumble_level(256) == UINT16_MAX);

    uint8_t actual[GFN_TRITON_RUMBLE_REPORT_SIZE];
    const uint8_t expected[GFN_TRITON_RUMBLE_REPORT_SIZE] = {
        0x80, 0x00, 0x00, 0x00, 0x34,
        0x12, 0x00, 0xcd, 0xab, 0x00,
    };
    gfn_build_triton_rumble_report(0x1234, 0xabcd, actual);
    assert(memcmp(actual, expected, sizeof(expected)) == 0);

    assert(gfn_test_next_rumble_wait_ms(100, 100, 1000) == 40);
    assert(gfn_test_next_rumble_wait_ms(139, 100, 1000) == 1);
    assert(gfn_test_next_rumble_wait_ms(140, 100, 1000) == 0);
    assert(gfn_test_next_rumble_wait_ms(100, 100, 130) == 30);
    assert(gfn_test_next_rumble_wait_ms(131, 100, 130) == 0);
    return 0;
}
