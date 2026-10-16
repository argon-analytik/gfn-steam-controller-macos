#!/bin/zsh
# One-shot preflight for the private Steam runtime, never a background service.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
SCRIPT_DIR="${0:A:h}"
if (( $# != 1 )) || [[ "$1" != /* ]]; then
    print -u2 'Usage: ensure-runtime.zsh PRIVATE_RUNTIME_APP'
    exit 64
fi
runtime="$1"
official=/Applications/GeForceNOW.app
if [[ "${runtime:A}" == "${official:A}" || -L "$runtime" || ! -d "$runtime" ]]; then
    print -u2 'Expected an existing private GFN runtime, separate from the official app.'
    exit 64
fi
source "$SCRIPT_DIR/lib/app-transaction.zsh"

# The descriptor lock releases on exit/crash. Two clicks cannot race a rebuild.
zmodload zsh/system
lock_file="${runtime:h}/.gfn-repair.lock"
[[ ! -L "$lock_file" ]] || exit 64
touch "$lock_file"
chmod 600 "$lock_file"
integer lock_fd
zsystem flock -t 1 -f lock_fd "$lock_file" || {
    print -u2 'A GFN repair is already in progress. Try again when it finishes.'
    exit 75
}

if "$SCRIPT_DIR/verify.zsh" "$runtime"; then
    exit 0
fi

# A normal NVIDIA update removes the bridge. Do not automatically replace a
# partially damaged custom build, an unrelated app or an unknown signature.
if ! app_is_unpatched_source "$runtime"; then
    print -u2 'The controller runtime is damaged and needs manual repair.'
    exit 1
fi
source_app="$(select_install_source "$official" "$runtime")"
fingerprint() {
    shasum -a 256 "$runtime/Contents/Info.plist" \
        "$runtime/Contents/MacOS/GeForceNOW" \
        "$runtime/Contents/Frameworks/libGeronimo.dylib"
}
before="$(fingerprint)"
work_dir="$(mktemp -d "${runtime:h}/.gfn-repair.XXXXXX")"
trap 'rm -rf -- "$work_dir"' EXIT
staged_app="$work_dir/GeForceNOW-Steam-Controller.app"
print 'GFN updated: restoring the controller bridge for the installed version.'

# build.zsh validates NVIDIA identity/signature and exact instruction pairs.
# Its output is staged; an unsupported update leaves the installed app intact.
"$SCRIPT_DIR/build.zsh" "$source_app" "$staged_app"
"$SCRIPT_DIR/verify.zsh" "$staged_app"
"$SCRIPT_DIR/reset-gfn-container.zsh"
if [[ "$(fingerprint)" != "$before" ]] || ! app_is_unpatched_source "$runtime"; then
    print -u2 'GFN changed during preparation. The current app was preserved.'
    exit 1
fi
run_admin() { "$@"; }
run_with_log() {
    local action="$1" log_file="$2"
    shift 2
    if "$@" >"$log_file" 2>&1; then return 0; fi
    print -u2 "$action failed:"
    cat "$log_file" >&2
    return 1
}
replace_verified_app "$staged_app" "$runtime" \
    "$SCRIPT_DIR/verify.zsh" "$work_dir/verification.log"
print 'Controller runtime repaired and verified. Steam profiles were preserved.'
