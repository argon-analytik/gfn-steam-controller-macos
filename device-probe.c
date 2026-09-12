#include "haptic_bridge.h"

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/hid/IOHIDKeys.h>
#include <IOKit/hid/IOHIDManager.h>
#include <stdio.h>
#include <stdlib.h>

static int property(IOHIDDeviceRef device, CFStringRef key) {
    CFTypeRef value = IOHIDDeviceGetProperty(device, key);
    int number = 0;
    if (value && CFGetTypeID(value) == CFNumberGetTypeID()) {
        CFNumberGetValue((CFNumberRef)value, kCFNumberIntType, &number);
    }
    return number;
}

int main(void) {
    // Metadata only: never opens a device or sends input/output reports.
    IOHIDManagerRef manager = IOHIDManagerCreate(kCFAllocatorDefault, 0);
    if (!manager) return 1;
    IOHIDManagerSetDeviceMatching(manager, NULL);
    CFSetRef devices = IOHIDManagerCopyDevices(manager);
    if (!devices) {
        CFRelease(manager);
        return 1;
    }
    CFIndex count = CFSetGetCount(devices);
    const void **items = calloc((size_t)count + 1, sizeof(*items));
    if (!items) {
        CFRelease(devices);
        CFRelease(manager);
        return 1;
    }
    CFSetGetValues(devices, items);
    unsigned selected = 0;
    unsigned virtual_gamepads = 0;
    for (CFIndex i = 0; i < count; i++) {
        IOHIDDeviceRef device = (IOHIDDeviceRef)items[i];
        int vendor = property(device, CFSTR(kIOHIDVendorIDKey));
        int product = property(device, CFSTR(kIOHIDProductIDKey));
        if (vendor == 0x28de && (product == 0x1303 || product == 0x1304)) {
            bool supported = gfn_is_supported_output_device(device);
            printf("steam_device=%04x:%04x primary_usage=%04x:%04x rumble_target=%s\n",
                   vendor, product,
                   property(device, CFSTR(kIOHIDPrimaryUsagePageKey)),
                   property(device, CFSTR(kIOHIDPrimaryUsageKey)),
                   supported ? "yes" : "no");
            if (supported) selected++;
        }
        if (vendor == 0x045e && product == 0x028e &&
            IOHIDDeviceConformsTo(device, 1, 5)) {
            virtual_gamepads++;
        }
    }
    printf("rumble_targets=%u xbox_compatible_gamepads=%u\n",
           selected, virtual_gamepads);
    free(items);
    CFRelease(devices);
    CFRelease(manager);
    return 0;
}
