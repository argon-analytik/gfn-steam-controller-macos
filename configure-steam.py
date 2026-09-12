#!/usr/bin/env python3
"""Prepare/install the existing GFN shortcut's layout and Steam-only launcher."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from steam_profile import bind_autosave, gamepad_profile, patch_shortcut, retune_gyro_profile, shortcut_appids, FINE_GYRO_MODE


def validate_launcher_info(info, gameid, runtime):
    identity = json.loads((Path(__file__).resolve().parent/'launcher/identity.json').read_text())
    expected = {'CFBundleIdentifier': identity['bundle_id'], 'CFBundleExecutable': identity['executable'],
                'SteamGameID': gameid, 'GFNRuntimePath': str(runtime)}
    if any(info.get(key) != value for key, value in expected.items()):
        raise ValueError('Launcher identity or route mismatch')


def verify_runtime(path):
    result = subprocess.run([str(Path(__file__).resolve().parent/'verify.zsh'), str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise RuntimeError('GFN verification failed:\n' + '\n'.join(result.stdout.splitlines()[-8:]))
    print('GFN patch and signature verified')


def stopped():
    output = subprocess.check_output(['/bin/ps', '-axo', 'uid=,comm='], text=True)
    names = {'steam_osx', 'steam', 'GeForceNOW', 'GeForceNOWStreamer', 'GeForceNOWContainer'}
    for row in output.splitlines():
        uid, _, command = row.strip().partition(' ')
        if uid == str(os.getuid()) and Path(command.strip()).name in names:
            raise RuntimeError('Quit Steam and GeForce NOW before configuring; an app is still running')


def atomic_write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def discover_target(steam, account=None, appid=None):
    """Find one exact-name non-Steam shortcut without printing account data."""
    if account is not None:
        paths = [steam / f'userdata/{account}/config/shortcuts.vdf']
    else:
        paths = sorted(steam.glob('userdata/[0-9]*/config/shortcuts.vdf'))
    matches = []
    for path in paths:
        if not path.is_file() or not path.parent.parent.name.isdigit():
            continue
        account_id = int(path.parent.parent.name)
        for shortcut_id in shortcut_appids(path.read_bytes()):
            if appid is None or shortcut_id == appid:
                matches.append((account_id, shortcut_id, path))
    if len(matches) != 1:
        raise ValueError('Expected exactly one Steam shortcut named GeForce NOW (Steam Controller)')
    return matches[0]


def install_transaction(visible, runtime, launcher, changes, originals, backup,
                        preflight=stopped, verify=verify_runtime):
    staged = visible.with_name(visible.name + '.staging-' + backup.name)
    if staged.exists():
        raise RuntimeError('Staging target already exists')
    runtime_moved = wrapper_saved = wrapper_installed = False
    written = []
    try:
        shutil.copytree(launcher, staged)
        preflight()
        for path, data in originals.items():
            if (path.read_bytes() if path.exists() else None) != data:
                raise RuntimeError('Steam configuration changed during preparation')
        if not runtime.exists():
            runtime.parent.mkdir(parents=True, exist_ok=True)
            visible.rename(runtime)
            runtime_moved = True
        else:
            visible.rename(backup/'previous-launcher.app')
            wrapper_saved = True
        staged.rename(visible)
        wrapper_installed = True
        for path, data in changes.items():
            atomic_write(path, data)
            written.append(path)
            if path.read_bytes() != data:
                raise RuntimeError('Steam configuration readback failed')
        verify(runtime)
    except BaseException as error:
        residual = []
        for path in reversed(written):
            # A concurrent edit is never replaced by an older backup.
            if not path.exists() or path.read_bytes() != changes[path]:
                residual.append(str(path))
            elif originals[path] is None:
                path.unlink()
            else:
                atomic_write(path, originals[path])
        if wrapper_installed:
            shutil.rmtree(visible)
        if runtime_moved:
            runtime.rename(visible)
        elif wrapper_saved:
            (backup/'previous-launcher.app').rename(visible)
        if residual:
            raise RuntimeError('Concurrent edits preserved during rollback; inspect backup ' + str(backup)) from error
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return runtime_moved


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--account', type=int, help='Steam account ID; discovered automatically when omitted')
    ap.add_argument('--appid', type=int, help='non-Steam shortcut AppID; discovered automatically when omitted')
    ap.add_argument('--launcher', type=Path)
    ap.add_argument('--gyro-only', action='store_true', help='Retune existing GFN gyro profiles without replacing apps or other controls')
    ap.add_argument('--configset', action='append', default=[], help='Additional existing configset filename')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    home = Path.home()
    steam = home / 'Library/Application Support/Steam'
    visible = home / 'Applications/GeForceNOW-Steam-Controller.app'
    runtime_root = home / 'Library/Application Support/gfn-steam-controller-macos'
    runtime = runtime_root / 'runtime/GeForceNOW-Steam-Controller.app'
    client = steam / 'Steam.AppBundle/Steam/Contents/MacOS'
    account, appid, shortcuts = discover_target(steam, args.account, args.appid)
    if not 0 < account < 2**32 or not 2**31 <= appid < 2**32:
        raise ValueError('Invalid account or non-Steam app ID')
    config = steam / f'steamapps/common/Steam Controller Configs/{account}/config'
    if not config.is_dir() or not shortcuts.is_file():
        raise ValueError('Existing Steam account/shortcut configuration not found')
    if args.gyro_only:
        # Validate the shortcut identity, but do not write its launch path.
        patch_shortcut(shortcuts.read_bytes(), appid, runtime, visible)
        paths = sorted((config/'geforce now (steam controller)').glob('*.vdf'))
        if not paths:
            raise ValueError('Existing GFN profiles not found')
        # Also remove the previous gyro assignment from our unused numeric profiles.
        paths += sorted((config/str(appid)).glob('*.vdf'))
        retune_profiles(paths, args.apply)
        return
    expected_gameid = str((appid << 32) | 0x02000000)
    launcher_temp = None
    launcher = args.launcher
    if launcher is None:
        launcher_temp = tempfile.TemporaryDirectory(prefix='gfn-steam-launcher-')
        launcher = Path(launcher_temp.name) / 'GeForceNOW-Steam-Controller.app'
        subprocess.run([str(Path(__file__).resolve().parent/'build-launcher.zsh'),
                        expected_gameid, str(runtime), str(launcher)], check=True)
    with (launcher/'Contents/Info.plist').open('rb') as f:
        info = plistlib.load(f)
    validate_launcher_info(info, expected_gameid, runtime)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(launcher)], check=True)
    source_runtime = runtime if runtime.exists() else visible
    verify_runtime(source_runtime)
    if runtime.exists():
        with (visible/'Contents/Info.plist').open('rb') as f:
            if plistlib.load(f).get('CFBundleIdentifier') != info['CFBundleIdentifier']:
                raise ValueError('Refusing to replace an unrelated visible application')
    template = (client/'controller_base/templates/controller_neptune_gamepad_fps.vdf').read_text(encoding='utf-8-sig')
    originals = {}
    changes = {}
    changes[shortcuts] = patch_shortcut(shortcuts.read_bytes(), appid, runtime, visible)
    # Steam's non-Steam controller configurations are keyed by the shortcut's
    # lower-case name. The numeric AppID is only the process/launch identity.
    profile_key = 'geforce now (steam controller)'
    for controller in ['controller_triton', 'controller_neptune']:
        profile = config / profile_key / (controller + '.vdf')
        changes[profile] = gamepad_profile(template, controller, account, profile)
    configsets = ['configset_controller_triton.vdf', 'configset_controller_neptune.vdf'] + args.configset
    for filename in dict.fromkeys(configsets):
        if Path(filename).name != filename or not filename.startswith('configset_') or not filename.endswith('.vdf'):
            raise ValueError('Invalid configset filename')
        path = config / filename
        if not path.is_file():
            raise ValueError('Expected existing controller configset')
        changes[path] = bind_autosave(path.read_bytes(), profile_key)
        # A per-device configset selects <serial>.vdf, not the type-wide file.
        # Steam does not fall through to that file when the serial file is absent.
        stem = filename[len('configset_'):-len('.vdf')]
        if stem not in ['controller_triton', 'controller_neptune']:
            if stem.startswith('controller_'):
                raise ValueError('Only Steam Controller 2 configsets are supported')
            profile = config / profile_key / (stem + '.vdf')
            changes[profile] = gamepad_profile(template, 'controller_triton', account, profile)
    for path in [visible, runtime, launcher, *changes]:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError('Refusing symlink targets')
    for path in changes:
        originals[path] = path.read_bytes() if path.exists() else None
    print(json.dumps({'apply': args.apply, 'files': len(changes), 'gameid': expected_gameid,
                      'runtime_move': not runtime.exists(), 'gyro_activation': 'R4 held', 'gyro_output': FINE_GYRO_MODE}))
    if not args.apply:
        return
    stopped()
    backup = runtime_root / 'backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True, mode=0o700)
    for index, (path, data) in enumerate(originals.items()):
        if data is not None:
            atomic_write(backup / f'{index}.original', data)
    manifest = [{'path': str(p), 'original': f'{i}.original' if data is not None else None,
                 'before_sha256': hashlib.sha256(data).hexdigest() if data is not None else None,
                 'after_sha256': hashlib.sha256(changes[p]).hexdigest()}
                for i, (p, data) in enumerate(originals.items())]
    atomic_write(backup/'files.json', json.dumps(manifest, indent=2).encode())
    def verify_install(path):
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(visible)], check=True)
        verify_runtime(path)
    runtime_moved = install_transaction(visible, runtime, launcher, changes, originals, backup,
                                        verify=verify_install)
    atomic_write(backup/'receipt.json', json.dumps({'installed': True, 'runtime_moved': runtime_moved,
                  'gameid': expected_gameid, 'physical_gameplay_verified': False}, indent=2).encode())
    print('Installed. Backup and receipt: ' + str(backup))


def retune_profiles(paths, apply):
    originals = {}
    changes = {}
    for path in paths:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError('Refusing symlink targets')
        data = path.read_bytes()
        changed = retune_gyro_profile(data)
        if changed != data:
            originals[path] = data
            changes[path] = changed
    print(json.dumps({'apply': apply, 'profiles': len(changes), 'gyro_activation': 'R4 held', 'gyro_output': FINE_GYRO_MODE,
                      'other_controls_changed': False, 'app_replacement': False}))
    if not apply or not changes:
        return
    stopped()
    backup = Path.home()/'Library/Application Support/gfn-steam-controller-macos/backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-gyro')
    backup.mkdir(parents=True, mode=0o700)
    manifest = []
    for index, (path, data) in enumerate(originals.items()):
        name = f'{index}.original'
        atomic_write(backup/name, data)
        manifest.append({'path': str(path), 'original': name,
                         'before_sha256': hashlib.sha256(data).hexdigest(),
                         'after_sha256': hashlib.sha256(changes[path]).hexdigest()})
    atomic_write(backup/'files.json', json.dumps(manifest, indent=2).encode())
    written = []
    try:
        stopped()
        for path, data in originals.items():
            if path.read_bytes() != data:
                raise RuntimeError('Steam configuration changed during preparation')
        for path, data in changes.items():
            atomic_write(path, data)
            written.append(path)
            if path.read_bytes() != data:
                raise RuntimeError('Profile readback failed')
    except BaseException as error:
        drifted = False
        for path in reversed(written):
            if path.exists() and path.read_bytes() == changes[path]:
                atomic_write(path, originals[path])
            else:
                drifted = True
        if drifted:
            raise RuntimeError('Concurrent edits preserved; inspect backup ' + str(backup)) from error
        raise
    atomic_write(backup/'receipt.json', json.dumps({'installed': True, 'gyro_activation': 'R4 held', 'gyro_output': FINE_GYRO_MODE,
                  'other_controls_changed': False, 'physical_gyro_verified': False}, indent=2).encode())
    print('Gyro updated. Backup and receipt: ' + str(backup))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print('Configuration stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
