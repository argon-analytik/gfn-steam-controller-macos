#!/usr/bin/env python3
"""Hide macOS's duplicate Steam Puck in Steam while retaining Valve's HID path."""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'lib'))
from steam_profile import get, parse

spec = importlib.util.spec_from_file_location('configure', ROOT / 'configure-steam.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)

DUPLICATE = '05ac/0004'


def exclude_apple_duplicate(text):
    """Change only the persistent Steam device exclusion, retaining other bytes."""
    root = parse(text)
    store = get(root, 'InstallConfigStore')
    if len(root) != 1 or not isinstance(store, list):
        raise ValueError('Unexpected Steam config structure')
    existing = get(store, 'controller_blacklist', None)
    if existing is not None and not isinstance(existing, str):
        raise ValueError('Invalid controller blacklist')
    matches = list(re.finditer(r'("controller_blacklist"\s+")([^"\r\n]*)(")', text))
    if len(matches) != (0 if existing is None else 1):
        raise ValueError('Ambiguous controller blacklist')
    devices = existing.split(',') if existing else []
    if any(not re.fullmatch(r'[0-9a-fA-F]{4}/[0-9a-fA-F]{4}', d) for d in devices):
        raise ValueError('Unexpected controller blacklist format')
    if DUPLICATE in [d.lower() for d in devices]:
        return text
    value = ','.join(devices + [DUPLICATE])
    if matches:
        m = matches[0]
        return text[:m.start(2)] + value + text[m.end(2):]
    opening = re.match(r'\ufeff?\s*"InstallConfigStore"\s*\{', text)
    if opening is None:
        raise ValueError('Unexpected Steam config header')
    newline = '\r\n' if '\r\n' in text else '\n'
    addition = newline + '\t"controller_blacklist"\t\t"' + value + '"'
    return text[:opening.end()] + addition + text[opening.end():]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    target = Path.home() / 'Library/Application Support/Steam/config/config.vdf'
    if target.is_symlink() or any(p.is_symlink() for p in target.parents):
        raise ValueError('Symlink target requires review')
    before = target.read_bytes()
    after = exclude_apple_duplicate(before.decode('utf-8')).encode('utf-8')
    print(json.dumps({'changed': before != after, 'apply': args.apply,
                      'excluded_duplicate': DUPLICATE, 'profiles_changed': False}))
    if not args.apply or before == after:
        return
    config.stopped()
    backup = Path.home() / 'Library/Application Support/gfn-steam-controller-macos/backups' / \
        datetime.datetime.now().strftime('%Y%m%d-%H%M%S-duplicate')
    backup.mkdir(parents=True, mode=0o700)
    config.atomic_write(backup/'config.original', before)
    if target.read_bytes() != before:
        raise RuntimeError('Steam config changed during preparation')
    config.atomic_write(target, after, target.stat().st_mode & 0o777)
    if target.read_bytes() != after:
        raise RuntimeError('Concurrent config change; inspect backup ' + str(backup))
    config.atomic_write(backup/'receipt.json', json.dumps({
        'target': str(target), 'before_sha256': hashlib.sha256(before).hexdigest(),
        'after_sha256': hashlib.sha256(after).hexdigest(), 'excluded_duplicate': DUPLICATE,
        'profiles_changed': False, 'runtime_verified': False}).encode())
    print('Backup: ' + str(backup))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        print('Stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
