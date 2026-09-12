#ifndef GFN_STEAM_HID_HAPTIC_BRIDGE_H
#define GFN_STEAM_HID_HAPTIC_BRIDGE_H

#include <stdint.h>
#include <stdbool.h>
#include <IOKit/hid/IOHIDDevice.h>

#define GFN_TRITON_RUMBLE_REPORT_SIZE 10

uint16_t gfn_map_rumble_level(int level);
bool gfn_is_supported_triton_output(
    int vendor_id, int product_id, bool has_vendor_collection,
    const char *transport);
bool gfn_is_supported_output_device(IOHIDDeviceRef device);
void gfn_build_triton_rumble_report(
    uint16_t low_frequency,
    uint16_t high_frequency,
    uint8_t report[GFN_TRITON_RUMBLE_REPORT_SIZE]);
int HIDSetRumbleTypeSine(
    int controller_id,
    int left,
    int right,
    int left_trigger,
    int right_trigger,
    int duration_ms);

#ifdef GFN_HAPTIC_TESTING
uint64_t gfn_test_next_rumble_wait_ms(
    uint64_t now_ms,
    uint64_t last_send_started_ms,
    uint64_t deadline_ms);
#endif

#endif
