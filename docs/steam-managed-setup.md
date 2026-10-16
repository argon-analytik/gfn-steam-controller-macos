# Steam-managed setup and recovery

This guide covers the launcher and generated Steam Controller layout added by
this community fork. The shorter patch-only installation remains documented in
the main README.

## What the setup changes

The setup keeps the user-facing app at:

```text
~/Applications/GeForceNOW-Steam-Controller.app
```

After configuration, that app is a small launcher. The patched NVIDIA runtime
moves to:

```text
~/Library/Application Support/gfn-steam-controller-macos/runtime/GeForceNOW-Steam-Controller.app
```

The launcher checks the private runtime, repairs supported NVIDIA updates, then
asks Steam to start the same non-Steam shortcut. Steam starts a signed ARM64
`steam-gfn-entry` helper beside the runtime. That helper uses `execv`, preserving
Steam's process tracking and controller context. The shortcut's AppID stays the same.

The setup edits only the matching non-Steam shortcut and its controller
configuration. It does not change global Desktop or Guide Button layouts.

## Installing

1. Install the official GeForce NOW and Steam applications.
2. Connect the Steam Controller through the official Puck or Bluetooth and
   confirm that Steam detects it.
3. Build the patched GFN copy:

   ```sh
   ./build.zsh
   ```

4. Add `~/Applications/GeForceNOW-Steam-Controller.app` to Steam as a
   non-Steam game. Rename it exactly to `GeForce NOW (Steam Controller)`.
   Steam may store the `.app` bundle or the executable inside it; both are accepted.
5. Open the shortcut's controller settings once so Steam creates the local
   controller configuration. Quit Steam and every GFN window.
6. Preview and apply the setup:

   ```sh
   ./configure-steam.py
   ./configure-steam.py --apply
   ```

The preview performs discovery and validation and builds a temporary launcher;
it does not change installed apps or Steam configuration. The apply step
repeats the checks immediately before each transaction.

Version 1.1.0 fixes the earlier “Shortcut identity changed” error for `.app`
targets. Keep your existing shortcut and rerun setup from the updated repository.
Existing installations receive the new launcher and native entrypoint through
the same commands. Do not rebuild over the visible launcher with `./build.zsh`.

If more than one Steam account contains the exact shortcut, select one with
`--account`. If one account contains more than one matching shortcut, use
`--appid`. These identifiers remain on the local Mac.

Some controllers use a device-specific configset. Add its existing filename to
both commands when the type-wide profile is not selected:

```sh
./configure-steam.py --configset configset_DEVICE.vdf
./configure-steam.py --configset configset_DEVICE.vdf --apply
```

## Controller layout

- left stick: movement;
- right stick: camera;
- right trackpad: camera;
- D-pad: digital D-pad directions;
- R4 held: direct gyro-to-mouse fine aiming;
- R4 released: no gyro output;
- L2, R2, stick clicks, buttons, and other template controls remain unchanged.

Direct mouse output avoids the streamed game's joystick deadzone. A game must
accept mouse and gamepad input at the same time for this mode to work as
intended.

Gyro uses Player Space, combining yaw and roll for horizontal aiming while
keeping pitch for vertical aiming. Its speed deadzone and precision threshold
are zero, so small movements are not deliberately filtered out.

For always-on gyro, use `--gyro-activation always` during setup or a gyro-only
update. `--gyro-activation r4` restores hold-to-enable. `--gyro-output joystick`
is an optional alternative for games that reject mixed input, but needs tuning
to that game's joystick deadzone and camera curve. Mouse output remains the default.

## Backups and receipts

Every applied setup or gyro-only change creates a directory below:

```text
~/Library/Application Support/gfn-steam-controller-macos/backups/
```

`files.json` records each destination, file modes, and before/after SHA-256 hashes.
`receipt.json` records the completed operation. Original Steam files are stored
beside those manifests with restrictive local permissions. Do not publish this
directory: its paths and Steam identifiers belong to the local account.

## Updating GeForce NOW

The updated launcher verifies the private runtime before each new session. If
NVIDIA replaced it with an unpatched, supported release, the launcher rebuilds
and verifies it before starting Steam. A damaged custom build or unknown
instruction signature stops with an error. Running streams are not replaced.
The launcher log is `~/Library/Logs/gfn-steam-controller-macos/launcher.log`.

For a manual update:

1. Update the official `/Applications/GeForceNOW.app` first.
2. Quit Steam and every GeForce NOW window.
3. Rebuild the private runtime directly from the official app:

   ```sh
   ./build.zsh /Applications/GeForceNOW.app \
     "$HOME/Library/Application Support/gfn-steam-controller-macos/runtime/GeForceNOW-Steam-Controller.app"
   ```

4. Verify it:

   ```sh
   ./verify.zsh \
     "$HOME/Library/Application Support/gfn-steam-controller-macos/runtime/GeForceNOW-Steam-Controller.app"
   ```

5. Open `~/Applications/GeForceNOW-Steam-Controller.app` and test the GFN
   interface, one streamed game, gyro aiming, and vibration.

The builder preserves the previous runtime as a timestamped sibling until the
new copy has passed verification. If NVIDIA changes a patched function, the
build stops on the unknown instruction sequence.

## Updating only the gyro settings

Quit Steam and GFN, preview the change, then apply it:

```sh
./configure-steam.py --gyro-only
./configure-steam.py --gyro-only --apply
```

For continuous aiming without R4:

```sh
./configure-steam.py --gyro-only --gyro-activation always
./configure-steam.py --gyro-only --gyro-activation always --apply
```

This mode changes only the known GFN gyro group and profile metadata. It
preserves the remaining controls, Steam shortcut, launcher, and NVIDIA runtime.

## Duplicate controller input

If Steam shows a second Apple-provided controller as well as Valve's Steam
Controller, it can interfere with input routing. For that specific condition,
`repair-controller-duplicates.py` can add `05ac/0004` to Steam's controller
exclusion list, preserving existing entries and backing up the configuration:

```sh
./repair-controller-duplicates.py
./repair-controller-duplicates.py --apply
```

Quit Steam and GFN first. This optional change applies to Steam's device list,
not only the GFN shortcut. It is not part of the normal setup.

## Optional Game Mode workaround

The patched GFN bundle opts out of Game Mode. The community launcher does not
change the Mac's global Game Mode policy. A separate `game-mode-guard.zsh` is
available for troubleshooting the macOS 27 hangs observed on the maintainer's
machine; their exact cause has not been established.

Running it explicitly forces Game Mode off for the **whole Mac** and needs
Xcode's `gamepolicyctl`. To restore automatic Game Mode after quitting GFN:

```sh
xcrun gamepolicyctl game-mode set auto
```

The community launcher leaves that restored policy alone.

## Rolling back the Steam-managed setup

Quit Steam and every GFN process before rollback. Use the latest setup backup,
not a `-gyro` backup.

1. Read `files.json` and confirm that every current destination still matches
   its recorded `after_sha256`. Stop if a file has changed since setup;
   restoring an older copy would overwrite a newer Steam edit.
2. Restore every numbered original to the exact destination listed in
   `files.json`. Remove a destination only when its manifest entry has
   `original: null` and its current hash still matches `after_sha256`.
   Restore `original_mode` for an existing native entrypoint as well.
3. Remove the small launcher at
   `~/Applications/GeForceNOW-Steam-Controller.app`.
4. Move the private runtime from Application Support back to that user
   Applications path.
5. Start Steam and verify that the original shortcut and controller selection
   are restored.

The patch-only `/Applications` install is independent and can still be removed
with `./uninstall.zsh`.

For a launcher **upgrade**, keep the runtime in place and restore the saved
`previous-launcher.app` instead of moving the runtime back. `receipt.json`
distinguishes these cases through `runtime_moved`. Never replace newer user
changes with an older backup.
