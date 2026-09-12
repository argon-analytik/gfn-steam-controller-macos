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

The launcher asks Steam to start the runtime through the exact non-Steam
shortcut. This keeps Steam Input active, forces the native arm64 executable,
and selects the generated GFN controller profile.

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
5. Open the shortcut's controller settings once so Steam creates the local
   controller configuration. Quit Steam and every GFN window.
6. Preview and apply the setup:

   ```sh
   ./configure-steam.py
   ./configure-steam.py --apply
   ```

The preview performs discovery and validation without writing. The apply step
repeats the checks immediately before each transaction.

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

## Backups and receipts

Every applied setup or gyro-only change creates a directory below:

```text
~/Library/Application Support/gfn-steam-controller-macos/backups/
```

`files.json` records each destination plus before/after SHA-256 hashes.
`receipt.json` records the completed operation. Original Steam files are stored
beside those manifests with restrictive local permissions. Do not publish this
directory: its paths and Steam identifiers belong to the local account.

## Updating GeForce NOW

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

This mode changes only the known GFN gyro group and profile metadata. It
preserves the remaining controls, Steam shortcut, launcher, and NVIDIA runtime.

## Rolling back the Steam-managed setup

Quit Steam and every GFN process before rollback. Use the latest setup backup,
not a `-gyro` backup.

1. Read `files.json` and confirm that every current destination still matches
   its recorded `after_sha256`. Stop if a file has changed since setup;
   restoring an older copy would overwrite a newer Steam edit.
2. Restore every numbered original to the exact destination listed in
   `files.json`. Remove a destination only when its manifest entry has
   `original: null` and its current hash still matches `after_sha256`.
3. Remove the small launcher at
   `~/Applications/GeForceNOW-Steam-Controller.app`.
4. Move the private runtime from Application Support back to that user
   Applications path.
5. Start Steam and verify that the original shortcut and controller selection
   are restored.

The patch-only `/Applications` install is independent and can still be removed
with `./uninstall.zsh`.
