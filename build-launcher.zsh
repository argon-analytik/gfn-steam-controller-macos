#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"
if (( $# != 3 )); then
    print -u2 'Usage: build-launcher.zsh STEAM_GAME_ID RUNTIME_APP OUTPUT_APP'
    exit 2
fi
game_id="$1"
runtime_app="$2"
output_app="$3"
[[ "$game_id" == <-> && "$runtime_app" == /* && "$output_app" == /* && ! -e "$output_app" ]]
mkdir -p "$output_app/Contents/MacOS" "$output_app/Contents/Resources"
tools_dir="$output_app/Contents/Resources/ControllerRepair"
mkdir -p "$tools_dir/lib"
for tool in ensure-runtime.zsh game-mode-guard.zsh build.zsh verify.zsh reset-gfn-container.zsh \
    patch_gc_backend.c patch_haptics.c haptic_bridge.c haptic_bridge.h \
    gfn-entitlements.plist; do
    cp "$tool" "$tools_dir/"
done
cp lib/app-transaction.zsh "$tools_dir/lib/"
chmod +x "$tools_dir"/*.zsh
entry_dir="$output_app/Contents/Resources/SteamEntry"
mkdir -p "$entry_dir"
cc -arch arm64 -Wall -Wextra -Werror -O2 steam-entry.c -o "$entry_dir/steam-gfn-entry"
codesign --force --sign - "$entry_dir/steam-gfn-entry"
codesign --verify --strict "$entry_dir/steam-gfn-entry"
xcrun swiftc -O -swift-version 6 -framework AppKit launcher/main.swift \
    -o "$output_app/Contents/MacOS/GFNSteamLauncher"
python3 - "$game_id" "$runtime_app" "$output_app" <<'PY'
from pathlib import Path
import json, plistlib, shutil, sys
game_id, runtime, output = sys.argv[1:]
if not 0 < int(game_id) < 2**64:
    raise SystemExit('Invalid Steam GameID')
identity = json.loads(Path('launcher/identity.json').read_text())
info = dict(CFBundleIdentifier=identity['bundle_id'],
    CFBundleName=identity['name'], CFBundleDisplayName=identity['display_name'],
    CFBundleExecutable=identity['executable'], CFBundlePackageType='APPL',
    CFBundleShortVersionString=identity['version'], CFBundleVersion=identity['build'], LSUIElement=True,
    LSMinimumSystemVersion='14.0', NSPrincipalClass='NSApplication',
    SteamGameID=game_id, GFNRuntimePath=runtime)
source = Path('/Applications/GeForceNOW.app/Contents')
if (source/'Info.plist').is_file():
    original = plistlib.loads((source/'Info.plist').read_bytes())
    icon = original.get('CFBundleIconFile', '')
    if icon and Path(icon).name == icon:
        if not icon.endswith('.icns'): icon += '.icns'
        if (source/'Resources'/icon).is_file():
            shutil.copyfile(source/'Resources'/icon, Path(output)/'Contents/Resources/GFN.icns')
            info['CFBundleIconFile'] = 'GFN.icns'
with (Path(output)/'Contents/Info.plist').open('wb') as f: plistlib.dump(info,f)
PY
codesign --force --sign - "$output_app"
codesign --verify --strict "$output_app"
python3 - "$output_app" <<'PY'
from pathlib import Path
import json, plistlib, sys
identity = json.loads(Path('launcher/identity.json').read_text())
app = Path(sys.argv[1])
info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
assert info['CFBundleIdentifier'] == identity['bundle_id']
assert info['CFBundleExecutable'] == identity['executable']
assert (app/'Contents/MacOS'/identity['executable']).is_file()
PY
print "Built launcher: $output_app"
