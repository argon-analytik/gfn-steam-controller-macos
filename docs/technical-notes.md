# Technical notes

## Steam shortcut and launcher

Steam may record a macOS non-Steam game as its `.app` bundle or as the binary
inside that bundle. Setup accepts those exact paths for the configured GFN
copy, not arbitrary `.app` suffixes. It preserves the shortcut's AppID and
rewrites its target to a small ARM64 helper beside the private runtime.

The helper replaces itself with GFN through `execv`, keeping the PID and Steam
parent relationship. The previous `/usr/bin/arch -arm64` target could fail with
Steam's process-spawn error. Calling `open` would delegate startup to LaunchServices
and lose this direct process relationship, so it is not used as the game target.

Before launching Steam, the visible launcher verifies the runtime. Repair uses
the existing staged build, exact signature checks, and guarded replacement
transaction. Unsupported updates leave the current runtime intact. The helper
also rejects a GFN runtime whose bridge marker is missing.

## Gyro

The generated layout uses Valve's Player Space conversion
(`gyro_to_2d_conversion_style=4`) and direct mouse output, with sensitivity 50,
zero speed deadzone, and zero precision threshold. This avoids the streamed
game's joystick deadzone and makes yaw/roll contribute to horizontal aiming
according to the controller's orientation. R4 is the default activation;
always-on is explicit. A game must support simultaneous mouse and gamepad input.

## Input path observed on the test machine

```text
Steam Controller (28de:1304)
        |
        v
     steam_osx
        |
        v
IOHIDUserDevice "GamePad-1" (Virtual, Microsoft, 045e:028e)
        |
        +--> unmodified GFN: GameController.framework -> input not usable
        |
        `--> patched GFN: native HID backend -> standard gamepad ID 0 -> stream
```

IORegistry identified `steam_osx` as the creator of the virtual device. A
read-only `IOHIDManager` probe matched `045e:028e` and received live axis and
button values, including button usage `0x0001` for the mapped A button. This
rules out a placeholder-only virtual device.

## Relevant GFN behavior

The unmodified app initialized its native GameController backend and logged:

```text
Enabled GameController.framework backend
Not handling device ... via HID because GameController will take it.
```

It then exposed Steam's `GamePad-1` through the Apple backend with a different
effective product identity and registered a standard gamepad, but the streamed
game did not receive usable input.

With `GCDeviceInit()` returning false, the same GFN build instead logged:

```text
Device Changed 45e 28e 0 1
handleNewGamepad: standard gamepad at effective ID: 0
```

Controller navigation then worked in both the GFN interface and streamed games.

## Why SDL is not part of the final fix

GFN `2.0.86.124` ships SDL `2.32.10`, which does not contain the newer direct
Steam Controller `28de:1304` HIDAPI driver. SDL 3.4.10 can read that hardware
directly, and `sdl2-compat` can expose it through the SDL2 ABI.

That experiment proved direct controller support but did not solve GFN because
GFN's controller pipeline selected its native Forge/GameController backend
instead of SDL joystick input. The final build therefore keeps NVIDIA's stock
SDL2 and changes only GameController backend initialization.

## Patch mechanics

The arm64 function currently begins with a standard stack-frame prologue:

```text
ff c3 00 d1  f4 4f 01 a9
```

The patch replaces those eight bytes with:

```text
00 00 80 52  c0 03 5f d6
```

which disassembles to:

```asm
mov w0, #0
ret
```

The builder resolves the function address dynamically, translates the Mach-O
virtual address to a file offset, and refuses any binary whose original bytes do
not match. This is intentionally narrower than searching for a byte sequence.

## Haptic bridge

GFN's HID backend did not advertise force feedback for Steam's virtual
`045e:028e` device, even though the streamed session delivered rumble commands.
The arm64 patch therefore makes `_Forge_isRumbleSupported` return true and
replaces `_Forge_setRumbleState` with a bounded stub that resolves
`HIDSetRumbleTypeSine` through `dlsym`.

The replacement `libGeronimo.dylib` exports that bridge and re-exports the
patched original as `libGeronimo.original.dylib`. The bridge runs only in the
main `GeForceNOW` process, opens physical Steam Controller interfaces matching
`28de:1304`, maps GFN's 8-bit motor levels to 16-bit amplitudes, and sends this
ten-byte output report:

```text
80 00 00 00 LL LL 00 HH HH 00
```

Changed motor states are forwarded immediately. While a state remains active,
the bridge refreshes the unchanged report on a 40 ms watchdog interval until
GFN's requested duration ends; an explicit zero-amplitude command or the
deadline stops both motors. The watchdog interval is measured from the start of
the preceding HID write, so the write's own latency does not accumulate into
the refresh period. This follows the timing model in
[SDL's Steam Triton driver](https://github.com/libsdl-org/SDL/blob/cc2713c0477118d3074b625abe8df7de7118fe2e/src/joystick/hidapi/SDL_hidapi_steam_triton.c),
which sends changed states directly and uses 40 ms only for hardware-watchdog
refreshes. Unit tests cover amplitude mapping, report encoding, watchdog
scheduling, the arm64 stub, idempotence, and rejection of unknown function
bytes. On the tested machine, vibration was directly felt during a streamed
game.

A runtime trace of GFN `2.0.87.130` observed motor levels from 0 through 231.
The bridge therefore preserves the full 0-255 input scale instead of saturating
levels at the previously assumed value of 30.

GFN `2.0.87.130` moved the relevant code and changed the relocation-dependent
`adrp` and `bl` encodings in both 64-byte haptic functions. Their control flow
and symbol layout remained the same. The patcher accepts the newly inspected
64-byte pair as a separate exact signature; it does not mask those changing
instructions or accept arbitrary function bodies.

GFN `2.0.88.129` retained the same haptic symbols, 64-byte function layout,
control flow, and file offsets (`0xd4bc` and `0xd4fc`). Its data relocation
moved by one page, changing the `adrp x8` instruction in both functions from
`c8 76 00 d0` to `08 77 00 d0`. The patcher accepts that inspected pair as a
third exact signature and continues to reject mixed or otherwise unknown
function bodies.

Re-signing the updated app can invalidate its previous Input Monitoring
approval. In that state gamepad input still works, GFN still dispatches rumble,
but `IOHIDManagerOpen` cannot open the physical controller. The bridge checks
`kIOHIDRequestTypeListenEvent` and registers an access request once when needed.
On the tested macOS release, `ListenEvent` does not display a normal permission
prompt: the user must enable GeForce NOW in **System Settings → Privacy &
Security → Input Monitoring** and relaunch the patched app before vibration can
resume.

The installer records the existing and staged apps' designated code
requirements before replacement. If they differ, it runs only
`tccutil reset ListenEvent com.nvidia.gfnpc.mall` after the new copy passes
installed verification. This removes a stale code-requirement decision but
does not grant access. `repair-input-monitoring.zsh` provides the same narrowly
scoped reset, launches the patched app so its request is registered, and opens
the relevant System Settings pane for explicit user approval.

GFN can self-update the separately installed patched bundle before the official
bundle is opened again. The updater removes `libGeronimo.original.dylib` and
restores an ordinary `libGeronimo.dylib`. When that unpatched installed copy is
newer than the official app, `install.zsh` may use it as a read-only build
source. An installed copy that still contains the bridge is never selected as
source. The builder also requires a valid deep signature, GFN's expected bundle
identifier, and NVIDIA Team ID `6KR3T733EC`; the staged candidate must then pass
the same instruction and signature verification before replacement.

## Resident BackgroundAgent collision

GFN intentionally keeps `GeForceNOWContainer` alive after the main window
closes. When a container from another GFN app copy owns
`ReliabilityMonitor/inst.lck` and the local message-bus port, the new copy's
mandatory `GfnBackgroundAgent` fails initialization. The UI reports
`backgroundagent: TimedOut` after 60 seconds and displays the generic **Problem
Detected** dialog even while streaming continues.

`reset-gfn-container.zsh` is a narrowly scoped troubleshooting utility for this
cross-copy collision. It will not terminate an active GFN window or streamer,
does not launch an app, and verifies that no container or reliability-lock
holder remains. After the reset, the user opens the desired app normally. The
behavior was verified live: the failing state changed from `TimedOut` to
`Success`, and the new container reached both `Initialized` and `Started`.

## Known side effects and future direction

The current workaround disables the GameController backend globally inside the
patched GFN process. A more surgical future implementation could exclude only
Steam's virtual `045e:028e` device from `GCHandlesDevice()` while preventing
duplicate registration. Such a change needs testing with Xbox, DualSense, and
other controllers before it can replace the current known-working patch.

The haptic bridge currently handles only controller ID 0 and the two main rumble
channels. Trigger-specific haptics are accepted by the ABI but ignored.
