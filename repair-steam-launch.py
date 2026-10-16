#!/usr/bin/env python3
"""Replace the legacy arch shortcut target with a native ARM64 exec helper."""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'lib'))
from steam_profile import patch_shortcut

spec = importlib.util.spec_from_file_location('gfn_configure', ROOT / 'configure-steam.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--account', required=True, type=int)
    ap.add_argument('--appid', required=True, type=int)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    if not 0 < a.account < 2**32 or not 2**31 <= a.appid < 2**32:
        raise ValueError('Invalid account or shortcut ID')
    home = Path.home()
    runtime = home / 'Library/Application Support/gfn-steam-controller-macos/runtime/GeForceNOW-Steam-Controller.app'
    entry = runtime.parent / 'steam-gfn-entry'
    shortcut = home / f'Library/Application Support/Steam/userdata/{a.account}/config/shortcuts.vdf'
    for p in (runtime, entry, shortcut):
        if p.is_symlink() or any(v.is_symlink() for v in p.parents):
            raise ValueError('Symlink target requires review')
    before = shortcut.read_bytes()
    after = patch_shortcut(before, a.appid, runtime, entry)
    previous = entry.read_bytes() if entry.exists() else None
    previous_mode = entry.stat().st_mode & 0o777 if entry.exists() else 0o755
    print(json.dumps({'apply': a.apply, 'shortcut_changed': before != after,
                      'controller_profiles_changed': False, 'runtime_replaced': False}))
    if not a.apply:
        return
    config.stopped()
    config.verify_runtime(runtime)
    with tempfile.TemporaryDirectory(prefix='gfn-entry-') as td:
        built = Path(td) / 'steam-gfn-entry'
        subprocess.run(['cc', '-arch', 'arm64', '-Wall', '-Wextra', '-Werror', '-O2',
                        str(ROOT / 'steam-entry.c'), '-o', str(built)], check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(built)], check=True)
        subprocess.run(['codesign', '--verify', '--strict', str(built)], check=True)
        if subprocess.check_output(['lipo', '-archs', str(built)], text=True).strip() != 'arm64':
            raise ValueError('Expected ARM64-only entrypoint')
        binary = built.read_bytes()
        config.stopped()
        if shortcut.read_bytes() != before or (entry.read_bytes() if entry.exists() else None) != previous:
            raise RuntimeError('Launch configuration changed during preparation')
        backup = home / 'Library/Application Support/gfn-steam-controller-macos/backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-launch')
        backup.mkdir(parents=True, mode=0o700)
        config.atomic_write(backup / 'shortcuts.original', before)
        if previous is not None:
            config.atomic_write(backup / 'entry.original', previous)
        config.atomic_write(backup / 'manifest.json', json.dumps({
            'shortcut': str(shortcut), 'entry': str(entry), 'entry_existed': previous is not None,
            'entry_previous_mode': previous_mode,
            'before_sha256': hashlib.sha256(before).hexdigest(),
            'after_sha256': hashlib.sha256(after).hexdigest(),
            'entry_sha256': hashlib.sha256(binary).hexdigest()}).encode())
        written = []
        try:
            config.stopped()
            if shortcut.read_bytes() != before or (entry.read_bytes() if entry.exists() else None) != previous:
                raise RuntimeError('Launch configuration changed before write')
            config.atomic_write(entry, binary, 0o755)
            written.append(entry)
            config.atomic_write(shortcut, after)
            written.append(shortcut)
            if entry.read_bytes() != binary or shortcut.read_bytes() != after:
                raise RuntimeError('Launch configuration readback failed')
        except BaseException as error:
            # Preserve unexpected concurrent changes rather than overwriting them.
            residual = []
            if shortcut in written:
                if shortcut.exists() and shortcut.read_bytes() == after:
                    config.atomic_write(shortcut, before)
                else:
                    residual.append(str(shortcut))
            if entry in written:
                if entry.exists() and entry.read_bytes() == binary:
                    if previous is None:
                        entry.unlink()
                    else:
                        config.atomic_write(entry, previous, previous_mode)
                else:
                    residual.append(str(entry))
            if residual:
                raise RuntimeError('Concurrent changes preserved; inspect backup ' + str(backup)) from error
            raise
        config.atomic_write(backup / 'receipt.json', json.dumps({
            'installed': True, 'steam_launch_verified': False,
            'controller_profiles_changed': False}).encode())
        print('Installed native Steam entrypoint. Backup: ' + str(backup))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print('Stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
