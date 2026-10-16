# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.1.0] - 2026-10-17

### Fixed

- Accept the exact GFN `.app` bundle path stored by macOS Steam, as well as
  its executable, during configuration. Quoted and unquoted paths with spaces
  or Unicode work; unrelated applications and ambiguous shortcuts remain rejected.
- Preserve the shortcut AppID, other games, and existing controller associations.
- Use a signed native ARM64 entrypoint instead of `/usr/bin/arch` for Steam launches.
- Support fresh Steam Controller setups with only a Triton configset.

### Added

- Exact haptic patch signatures for GFN `2.0.89.141`.
- Runtime verification and transactional repair after supported NVIDIA updates.
- Player Space gyro and optional `--gyro-activation always`; R4 remains the default.
- Optional duplicate-controller repair and Game Mode troubleshooting tools.
  Normal community startup does not change the global Game Mode policy.
- Installer regression coverage for bundle targets, first setup, upgrades,
  preserved file modes, and rollback; no real Steam account is used by tests.

## [1.0.0] - 2026-09-12

### Added

- Steam-managed launcher that retains the native arm64 shortcut and active
  Steam Input context.
- Generated GFN layout with distinct stick outputs, digital D-pad bindings,
  right-trackpad camera control, and direct gyro-to-mouse aiming while R4 is held.
- Automatic account and shortcut discovery for unambiguous Steam setups.
- Guarded Steam configuration writes with backup, drift detection, readback,
  rollback, and a gyro-only update mode.
- Metadata-only device probe and optional Bluetooth rumble target filtering.

## [0.3.1] - 2026-09-01

### Changed

- add exact haptic-function signatures for GeForce NOW `2.0.88.129` while
  retaining fail-closed rejection of unknown or mixed-version function pairs;
- list GeForce NOW `2.0.88.129` as the current tested release.

## [0.3.0] - 2026-08-03

### Added

- add `repair-input-monitoring.zsh`, which performs an app-scoped permission
  reset and opens both the patched app and the relevant System Settings pane.

### Changed

- list GeForce NOW `2.0.87.131` as the current tested release;
- preserve GFN's full 8-bit rumble intensity range instead of saturating every
  motor level at or above 30 to full strength;
- forward changed rumble states immediately while retaining 40 ms watchdog
  refreshes, instead of delaying every state change with a blocking sleep;
- reuse a newer self-updated, now-unpatched installed copy as the build source
  instead of replacing it with an older official app.

### Fixed

- reset stale Input Monitoring automatically when installation changes the app
  signature;
- direct users to the manual Input Monitoring switch when macOS registers the
  request without displaying a permission prompt.

## [0.2.1] - 2026-07-22

### Changed

- add exact haptic-function signatures for GeForce NOW `2.0.87.130` while
  retaining fail-closed rejection of unknown binaries;
- explicitly request Input Monitoring when an updated ad-hoc build no longer
  has permission to open the physical Steam Controller for vibration;
- document the app-scoped `tccutil` recovery used when macOS retains a stale
  Input Monitoring denial after an update;
- list GeForce NOW `2.0.87.130` as the current tested release;
- the README now leads with the affected Steam Controller (2026) symptoms and
  answers common gamepad-routing questions.

## [0.2.0] - 2026-07-14

### Added

- fail-closed arm64 patches for GFN rumble capability and dispatch;
- a local HID bridge for physical Steam Controller vibration;
- unit tests for rumble mapping, report encoding, haptic patching, and reset
  utility argument validation;
- installer and uninstaller scripts for the standard system Applications
  folder, including installed-build verification and rollback;
- isolated transaction tests for successful replacement, verifier-triggered
  rollback, and idempotent removal;
- an opt-in troubleshooting utility that resets resident
  `GeForceNOWContainer` collisions without becoming the normal app launcher.

### Changed

- the verifier now checks the haptic patch, bridge re-export, original library,
  Finder display name, and deep app signature;
- the default bundle and Finder display name is now
  `GeForceNOW-Steam-Controller`;
- the normal installation path is now
  `/Applications/GeForceNOW-Steam-Controller.app`, so the patched copy appears
  in Finder's standard Applications folder;
- documentation now covers Input Monitoring, verified vibration, and GFN's
  mandatory BackgroundAgent timeout;
- documentation now states the possible GeForce NOW Terms of Use and account
  risks of running a modified client;
- CI now pins third-party Actions to immutable commits and receives automated
  GitHub Actions dependency update proposals;
- the security policy now constrains elevated installation operations to the
  fixed patched-app target.

## [0.1.0] - 2026-07-14

### Added

- fail-closed arm64 patcher for GFN `_GCDeviceInit`;
- staged builder that preserves the official app and previous patched builds;
- read-only verifier for patch state and code signature;
- unit tests for unpatched, patched, idempotent, and rejected byte sequences;
- documentation of the verified Steam virtual-HID input path and limitations;
- macOS GitHub Actions workflow.
