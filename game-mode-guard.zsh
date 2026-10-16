#!/bin/zsh
# The app's Info.plist opt-out was ignored for Steam-owned GFN on macOS 27.
# This is a global policy override on this Mac, with `set auto` as the rollback.
set -euo pipefail

gfn_force_game_mode_off() {
    local policy
    policy="$("$@" game-mode status)" || return 1
    if [[ "$policy" == *'Game mode is forced always off.'* ]]; then
        print 'Game Mode policy: forced off (Mac-wide).'
        return 0
    fi
    if [[ "$policy" != *'Game mode enablement policy is currently automatic.'* &&
          "$policy" != *'Game mode is forced always on.'* ]]; then
        print -u2 'Game Mode policy could not be verified; GFN will not start.'
        return 1
    fi
    "$@" game-mode set off || return 1
    policy="$("$@" game-mode status)" || return 1
    if [[ "$policy" != *'Game mode is forced always off.'* ]]; then
        print -u2 'Game Mode did not remain forced off; GFN will not start.'
        return 1
    fi
    print 'Game Mode policy: forced off (Mac-wide). Restore with: xcrun gamepolicyctl game-mode set auto'
}

if [[ "$ZSH_EVAL_CONTEXT" == toplevel ]]; then
    (( $# == 0 )) || exit 64
    gfn_force_game_mode_off /usr/bin/xcrun gamepolicyctl
fi
