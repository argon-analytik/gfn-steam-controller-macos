/* Native Steam shortcut target. exec preserves Steam's PID tracking and input
 * context; unlike /usr/bin/open it does not delegate the launch to launchd. */
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int bridge_is_present(const char *executable) {
    const char *suffix = "/Contents/MacOS/GeForceNOW";
    size_t length = strlen(executable), suffix_length = strlen(suffix);
    if (length < suffix_length || strcmp(executable + length - suffix_length, suffix) != 0)
        return 1;
    char library[PATH_MAX];
    int count = snprintf(library, sizeof(library), "%.*s/Contents/Frameworks/libGeronimo.original.dylib",
                         (int)(length - suffix_length), executable);
    return count > 0 && (size_t)count < sizeof(library) && access(library, R_OK) == 0;
}

int main(int argc, char **argv) {
    if (argc != 2 || argv[1][0] != '/') {
        fputs("Expected one absolute GeForce NOW executable path\n", stderr);
        return 64;
    }
    if (!bridge_is_present(argv[1])) {
        fputs("GFN was updated and needs controller repair. Open GeForceNOW-Steam-Controller.app from Applications.\n", stderr);
        return 78;
    }
    char *args[] = {argv[1], NULL};
    execv(argv[1], args);
    fprintf(stderr, "Cannot start GeForce NOW: %s\n", strerror(errno));
    return 126;
}
