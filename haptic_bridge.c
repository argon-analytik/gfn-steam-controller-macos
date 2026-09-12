#define _DARWIN_C_SOURCE

#include "haptic_bridge.h"

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/hid/IOHIDKeys.h>
#include <IOKit/hid/IOHIDManager.h>
#include <IOKit/hidsystem/IOHIDLib.h>
#include <mach-o/dyld.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define STEAM_VENDOR_ID 0x28de
#define STEAM_TRITON_PRODUCT_ID 0x1304
#define STEAM_TRITON_BLUETOOTH_PRODUCT_ID 0x1303
#define STEAM_TRITON_USAGE_PAGE 0xff00
#define STEAM_TRITON_USAGE 0x01
#define GFN_RUMBLE_MAX_LEVEL UINT8_MAX
#define TRITON_RUMBLE_RESEND_MS 40
#define MAX_HID_INTERFACES 16

struct bridge_state {
    pthread_mutex_t lock;
    pthread_cond_t changed;
    bool active;
    bool stop_pending;
    uint16_t low;
    uint16_t high;
    uint64_t deadline_ms;
    uint64_t generation;
};

struct bridge_devices {
    IOHIDManagerRef manager;
    IOHIDDeviceRef devices[MAX_HID_INTERFACES];
    size_t count;
};

static bool access_request_attempted;

static struct bridge_state state = {
    .lock = PTHREAD_MUTEX_INITIALIZER,
    .changed = PTHREAD_COND_INITIALIZER,
};

static uint64_t monotonic_ms(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        return 0;
    }
    return (uint64_t)value.tv_sec * 1000U + (uint64_t)value.tv_nsec / 1000000U;
}

uint16_t gfn_map_rumble_level(int level) {
    if (level <= 0) {
        return 0;
    }
    if (level >= GFN_RUMBLE_MAX_LEVEL) {
        return UINT16_MAX;
    }
    return (uint16_t)(((uint32_t)level * UINT16_MAX +
                       GFN_RUMBLE_MAX_LEVEL / 2) /
                      GFN_RUMBLE_MAX_LEVEL);
}

void gfn_build_triton_rumble_report(
    uint16_t low_frequency,
    uint16_t high_frequency,
    uint8_t report[GFN_TRITON_RUMBLE_REPORT_SIZE]) {
    static const uint8_t empty[GFN_TRITON_RUMBLE_REPORT_SIZE] = {0};
    memcpy(report, empty, sizeof(empty));
    report[0] = 0x80;
    report[4] = (uint8_t)(low_frequency & 0xffU);
    report[5] = (uint8_t)(low_frequency >> 8U);
    report[7] = (uint8_t)(high_frequency & 0xffU);
    report[8] = (uint8_t)(high_frequency >> 8U);
}

static uint64_t next_rumble_wait_ms(
    uint64_t now_ms,
    uint64_t last_send_started_ms,
    uint64_t deadline_ms) {
    uint64_t resend_ms = last_send_started_ms + TRITON_RUMBLE_RESEND_MS;
    uint64_t wake_ms = resend_ms < deadline_ms ? resend_ms : deadline_ms;
    return wake_ms > now_ms ? wake_ms - now_ms : 0;
}

#ifdef GFN_HAPTIC_TESTING
uint64_t gfn_test_next_rumble_wait_ms(
    uint64_t now_ms,
    uint64_t last_send_started_ms,
    uint64_t deadline_ms) {
    return next_rumble_wait_ms(
        now_ms, last_send_started_ms, deadline_ms);
}
#endif

static int number_property(IOHIDDeviceRef device, CFStringRef key) {
    CFTypeRef value = IOHIDDeviceGetProperty(device, key);
    int result = 0;
    if (value != NULL && CFGetTypeID(value) == CFNumberGetTypeID()) {
        (void)CFNumberGetValue((CFNumberRef)value, kCFNumberIntType, &result);
    }
    return result;
}

bool gfn_is_supported_triton_output(
    int vendor_id, int product_id, bool has_vendor_collection,
    const char *transport) {
    if (vendor_id != STEAM_VENDOR_ID || !has_vendor_collection ||
        transport == NULL) {
        return false;
    }
    if (product_id == STEAM_TRITON_PRODUCT_ID) {
        return strcmp(transport, "USB") == 0;
    }
    if (product_id == STEAM_TRITON_BLUETOOTH_PRODUCT_ID) {
        return strcmp(transport, "Bluetooth") == 0 ||
               strcmp(transport, "Bluetooth Low Energy") == 0;
    }
    return false;
}

bool gfn_is_supported_output_device(IOHIDDeviceRef device) {
    if (device == NULL ||
        number_property(device, CFSTR(kIOHIDMaxOutputReportSizeKey)) <
            GFN_TRITON_RUMBLE_REPORT_SIZE) {
        return false;
    }
    CFTypeRef property = IOHIDDeviceGetProperty(
        device, CFSTR(kIOHIDTransportKey));
    char transport[64];
    if (property == NULL || CFGetTypeID(property) != CFStringGetTypeID() ||
        !CFStringGetCString((CFStringRef)property, transport, sizeof(transport),
                            kCFStringEncodingUTF8)) {
        return false;
    }
    return gfn_is_supported_triton_output(
        number_property(device, CFSTR(kIOHIDVendorIDKey)),
        number_property(device, CFSTR(kIOHIDProductIDKey)),
        // Puck and Bluetooth are composite devices whose primary usage is mouse.
        IOHIDDeviceConformsTo(device, STEAM_TRITON_USAGE_PAGE,
                             STEAM_TRITON_USAGE), transport);
}

static void close_devices(struct bridge_devices *devices) {
    for (size_t i = 0; i < devices->count; ++i) {
        IOHIDDeviceClose(devices->devices[i], kIOHIDOptionsTypeNone);
        CFRelease(devices->devices[i]);
    }
    devices->count = 0;
    if (devices->manager != NULL) {
        IOHIDManagerClose(devices->manager, kIOHIDOptionsTypeNone);
        CFRelease(devices->manager);
        devices->manager = NULL;
    }
}

static bool ensure_input_monitoring_access(void) {
    IOHIDAccessType access =
        IOHIDCheckAccess(kIOHIDRequestTypeListenEvent);
    if (access == kIOHIDAccessTypeGranted) {
        return true;
    }
    if (!access_request_attempted) {
        access_request_attempted = true;
        (void)IOHIDRequestAccess(kIOHIDRequestTypeListenEvent);
    }
    return IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) ==
           kIOHIDAccessTypeGranted;
}

static bool open_devices(struct bridge_devices *devices) {
    close_devices(devices);

    if (!ensure_input_monitoring_access()) {
        return false;
    }

    devices->manager = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
    if (devices->manager == NULL) {
        return false;
    }

    int vendor = STEAM_VENDOR_ID;
    CFNumberRef vendor_number = CFNumberCreate(
        kCFAllocatorDefault, kCFNumberIntType, &vendor);
    if (vendor_number == NULL) {
        close_devices(devices);
        return false;
    }

    const void *keys[] = {
        CFSTR(kIOHIDVendorIDKey),
    };
    const void *values[] = {vendor_number};
    CFDictionaryRef matching = CFDictionaryCreate(
        kCFAllocatorDefault, keys, values, 1,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFRelease(vendor_number);
    if (matching == NULL) {
        close_devices(devices);
        return false;
    }

    IOHIDManagerSetDeviceMatching(devices->manager, matching);
    CFRelease(matching);
    if (IOHIDManagerOpen(devices->manager, kIOHIDOptionsTypeNone) !=
        kIOReturnSuccess) {
        close_devices(devices);
        return false;
    }

    CFSetRef set = IOHIDManagerCopyDevices(devices->manager);
    if (set == NULL) {
        close_devices(devices);
        return false;
    }
    CFIndex count = CFSetGetCount(set);
    const void **items = calloc((size_t)count, sizeof(*items));
    if (items == NULL) {
        CFRelease(set);
        close_devices(devices);
        return false;
    }
    CFSetGetValues(set, items);
    for (CFIndex i = 0; i < count && devices->count < MAX_HID_INTERFACES; ++i) {
        IOHIDDeviceRef device = (IOHIDDeviceRef)items[i];
        if (!gfn_is_supported_output_device(device)) {
            continue;
        }
        if (IOHIDDeviceOpen(device, kIOHIDOptionsTypeNone) != kIOReturnSuccess) {
            continue;
        }
        CFRetain(device);
        devices->devices[devices->count++] = device;
    }
    free(items);
    CFRelease(set);
    return devices->count > 0;
}

static bool send_report(
    struct bridge_devices *devices,
    uint16_t low,
    uint16_t high) {
    if (devices->count == 0 && !open_devices(devices)) {
        return false;
    }

    uint8_t report[GFN_TRITON_RUMBLE_REPORT_SIZE];
    gfn_build_triton_rumble_report(low, high, report);
    bool sent = false;
    for (size_t i = 0; i < devices->count; ++i) {
        IOReturn result = IOHIDDeviceSetReport(
            devices->devices[i], kIOHIDReportTypeOutput, report[0], report,
            sizeof(report));
        if (result == kIOReturnSuccess) {
            sent = true;
        }
    }
    if (!sent) {
        close_devices(devices);
    }
    return sent;
}

static void *rumble_worker(void *unused) {
    (void)unused;
    struct bridge_devices devices = {0};
    uint64_t handled_generation = 0;
    uint64_t last_send_started_ms = 0;

    for (;;) {
        pthread_mutex_lock(&state.lock);
        for (;;) {
            uint64_t now_ms = monotonic_ms();
            if (state.active && now_ms >= state.deadline_ms) {
                state.active = false;
                state.stop_pending = true;
                ++state.generation;
            }

            if (state.stop_pending || state.generation != handled_generation) {
                break;
            }
            if (!state.active) {
                pthread_cond_wait(&state.changed, &state.lock);
                continue;
            }

            uint64_t wait_ms = next_rumble_wait_ms(
                now_ms, last_send_started_ms, state.deadline_ms);
            if (wait_ms == 0) {
                break;
            }
            struct timespec wait = {
                .tv_sec = (time_t)(wait_ms / 1000U),
                .tv_nsec = (long)(wait_ms % 1000U) * 1000000L,
            };
            (void)pthread_cond_timedwait_relative_np(
                &state.changed, &state.lock, &wait);
        }

        bool stop = state.stop_pending;
        uint16_t low = stop ? 0 : state.low;
        uint16_t high = stop ? 0 : state.high;
        uint64_t generation = state.generation;
        state.stop_pending = false;
        pthread_mutex_unlock(&state.lock);

        // Start the watchdog clock before the blocking HID write, as SDL does.
        last_send_started_ms = monotonic_ms();
        (void)send_report(&devices, low, high);
        // A changed generation makes an event received during the write run next.
        handled_generation = generation;
    }
    return NULL;
}

__attribute__((visibility("default"))) int HIDSetRumbleTypeSine(
    int controller_id,
    int left,
    int right,
    int left_trigger,
    int right_trigger,
    int duration_ms) {
    (void)left_trigger;
    (void)right_trigger;
    if (controller_id != 0) {
        return 0;
    }

    uint16_t low = gfn_map_rumble_level(left);
    uint16_t high = gfn_map_rumble_level(right);
    pthread_mutex_lock(&state.lock);
    state.low = low;
    state.high = high;
    ++state.generation;
    if (low == 0 && high == 0) {
        state.active = false;
        state.stop_pending = true;
    } else {
        if (duration_ms <= 0) {
            duration_ms = 1000;
        } else if (duration_ms > 60000) {
            duration_ms = 60000;
        }
        state.active = true;
        state.stop_pending = false;
        state.deadline_ms = monotonic_ms() + (uint64_t)duration_ms;
    }
    pthread_cond_signal(&state.changed);
    pthread_mutex_unlock(&state.lock);
    return 1;
}

static bool is_main_geforce_now_process(void) {
    char path[PATH_MAX];
    uint32_t size = sizeof(path);
    if (_NSGetExecutablePath(path, &size) != 0) {
        return false;
    }
    const char *name = strrchr(path, '/');
    name = name == NULL ? path : name + 1;
    return strcmp(name, "GeForceNOW") == 0;
}

__attribute__((constructor)) static void install_haptic_bridge(void) {
    if (!is_main_geforce_now_process()) {
        return;
    }

    (void)ensure_input_monitoring_access();

    pthread_t worker;
    if (pthread_create(&worker, NULL, rumble_worker, NULL) != 0) {
        fputs("GFN Steam HID haptic worker could not start\n", stderr);
        return;
    }
    pthread_detach(worker);
}
