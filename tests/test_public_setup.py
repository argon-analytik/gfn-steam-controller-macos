"""Exercise the complete community setup using a synthetic Steam account."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_steam_profile import binary, shortcut, template
from steam_profile import dump, get, parse, shortcut_spans

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_setup', ROOT / 'configure-steam.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PublicSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'Test Person Å'
        self.steam = self.home / 'Library/Application Support/Steam'
        self.visible = self.home / 'Applications/GeForceNOW-Steam-Controller.app'
        self.runtime = self.home / 'Library/Application Support/gfn-steam-controller-macos/runtime/GeForceNOW-Steam-Controller.app'
        self.entry = self.runtime.parent / 'steam-gfn-entry'
        (self.visible / 'Contents').mkdir(parents=True)
        (self.visible / 'original-runtime').write_text('preserve')
        self.shortcuts = self.steam / 'userdata/1/config/shortcuts.vdf'
        self.shortcuts.parent.mkdir(parents=True)
        rows = shortcut()
        rows[0][1][0][1][2] = ('Exe', '"' + str(self.visible) + '"')
        self.before = binary(rows)
        self.shortcuts.write_bytes(self.before)
        self.config = self.steam / 'steamapps/common/Steam Controller Configs/1/config'
        self.config.mkdir(parents=True)
        # A new Triton user does not need a previous Neptune controller.
        self.configset = self.config / 'configset_controller_triton.vdf'
        self.configset.write_text('"controller_config" { "another game" { "workshop" "42" } }')
        client = self.steam / 'Steam.AppBundle/Steam/Contents/MacOS/controller_base/templates'
        client.mkdir(parents=True)
        (client / 'controller_neptune_gamepad_fps.vdf').write_text(dump(template()))
        self.launcher = self.home / 'built-launcher.app'
        contents = self.launcher / 'Contents'
        entry = contents / 'Resources/SteamEntry/steam-gfn-entry'
        entry.parent.mkdir(parents=True)
        entry.write_bytes(b'native-entry-fixture')
        info = json.loads((ROOT / 'launcher/identity.json').read_text())
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': info['bundle_id'], 'CFBundleExecutable': info['executable'],
            'SteamGameID': str((3000000000 << 32) | 0x02000000), 'GFNRuntimePath': str(self.runtime)}))

    def run_setup(self, *args):
        output = io.StringIO()
        with patch.object(Path, 'home', return_value=self.home), \
             patch.object(setup.sys, 'argv', ['configure-steam.py', '--account', '1', '--launcher', str(self.launcher), *args]), \
             patch.object(setup, 'verify_runtime'), patch.object(setup, 'stopped'), \
             patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(setup.subprocess, 'check_output', return_value='arm64\n'), \
             contextlib.redirect_stdout(output):
            setup.main()
        return output.getvalue()

    def test_reported_bundle_path_previews_without_changing_installed_files(self):
        output = self.run_setup()
        self.assertIn('"native_steam_entrypoint": true', output)
        self.assertEqual(self.shortcuts.read_bytes(), self.before)
        self.assertTrue(self.visible.exists())
        self.assertFalse(self.runtime.exists())
        self.assertFalse(self.entry.exists())

    def test_reported_bundle_path_installs_native_entry_and_r4_profile(self):
        self.run_setup('--apply')
        self.assertEqual((self.runtime / 'original-runtime').read_text(), 'preserve')
        self.assertEqual(self.entry.read_bytes(), b'native-entry-fixture')
        self.assertEqual(self.entry.stat().st_mode & 0o777, 0o755)
        rows = shortcut_spans(self.shortcuts.read_bytes())
        fields = {k.lower(): v for k, _, v, _, _ in rows[0][2][0][2]}
        self.assertEqual(fields['appid'], 3000000000)
        self.assertEqual(fields['exe'], '"' + str(self.entry) + '"')
        self.assertEqual(fields['launchoptions'], '"' + str(self.runtime / 'Contents/MacOS/GeForceNOW') + '"')
        def unrelated_fields(parsed):
            return [(k, kind, value) for k, kind, value, _, _ in parsed[0][2][1][2]]
        self.assertEqual(unrelated_fields(rows), unrelated_fields(shortcut_spans(self.before)))
        profile = parse((self.config / 'geforce now (steam controller)/controller_triton.vdf').read_text())
        gyro = next(v for k, v in get(profile, 'controller_mappings') if k == 'group' and get(v, 'mode') == 'gyro_to_mouse')
        self.assertEqual(get(get(gyro, 'settings'), 'gyro_ratchet_button_mask'), str(1 << 42))
        self.assertEqual(get(get(gyro, 'settings'), 'gyro_to_2d_conversion_style'), '4')
        self.assertEqual(get(get(parse(self.configset.read_text()), 'controller_config'), 'another game'), [('workshop', '42')])

    def test_always_on_is_explicit_and_existing_setup_can_be_updated(self):
        self.run_setup('--apply')
        self.run_setup('--gyro-only', '--gyro-activation', 'always', '--apply')
        profile = parse((self.config / 'geforce now (steam controller)/controller_triton.vdf').read_text())
        gyro = next(v for k, v in get(profile, 'controller_mappings') if k == 'group' and get(v, 'mode') == 'gyro_to_mouse')
        self.assertEqual(get(get(gyro, 'settings'), 'gyro_ratchet_button_mask'), '0')
        # A full launcher upgrade keeps the native route and the original runtime.
        self.run_setup('--apply')
        self.assertEqual((self.runtime / 'original-runtime').read_text(), 'preserve')

    def test_foreign_app_is_rejected_before_any_install(self):
        rows = shortcut()
        rows[0][1][0][1][2] = ('Exe', '"/Applications/Unrelated.app"')
        original = binary(rows)
        self.shortcuts.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'Shortcut identity'):
            self.run_setup('--apply')
        self.assertEqual(self.shortcuts.read_bytes(), original)
        self.assertTrue(self.visible.exists())
        self.assertFalse(self.runtime.exists())

    def test_ambiguous_account_requires_an_explicit_selection(self):
        self.assertEqual(setup.discover_target(self.steam)[:2], (1, 3000000000))
        another = self.steam / 'userdata/2/config/shortcuts.vdf'
        another.parent.mkdir(parents=True)
        another.write_bytes(self.before)
        with self.assertRaises(ValueError):
            setup.discover_target(self.steam)
        self.assertEqual(setup.discover_target(self.steam, account=1)[:2], (1, 3000000000))

    def test_failed_upgrade_restores_native_helper_bytes_and_permissions(self):
        self.run_setup('--apply')
        self.entry.write_bytes(b'previous native helper')
        self.entry.chmod(0o751)
        before = self.shortcuts.read_bytes()
        real_write = setup.atomic_write
        def fail_shortcut(path, data, mode=0o600):
            if path == self.shortcuts:
                raise OSError('simulated shortcut write failure')
            return real_write(path, data, mode)
        with patch.object(setup, 'atomic_write', side_effect=fail_shortcut), self.assertRaises(OSError):
            self.run_setup('--apply')
        self.assertEqual(self.entry.read_bytes(), b'previous native helper')
        self.assertEqual(self.entry.stat().st_mode & 0o777, 0o751)
        self.assertEqual(self.shortcuts.read_bytes(), before)
        self.assertEqual((self.runtime / 'original-runtime').read_text(), 'preserve')

    def test_real_launcher_build_packages_signed_native_entry_and_repair_tools(self):
        output = self.home / 'built smoke launcher.app'
        result = subprocess.run([str(ROOT / 'build-launcher.zsh'),
                                 str((3000000000 << 32) | 0x02000000), str(self.runtime), str(output)],
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        info = plistlib.loads((output / 'Contents/Info.plist').read_bytes())
        identity = json.loads((ROOT / 'launcher/identity.json').read_text())
        self.assertEqual(info['CFBundleIdentifier'], identity['bundle_id'])
        self.assertEqual(info['CFBundleShortVersionString'], identity['version'])
        helper = output / 'Contents/Resources/SteamEntry/steam-gfn-entry'
        self.assertEqual(subprocess.check_output(['lipo', '-archs', str(helper)], text=True).strip(), 'arm64')
        subprocess.run(['codesign', '--verify', '--strict', str(helper)], check=True, capture_output=True)
        repair = (output / 'Contents/Resources/ControllerRepair/ensure-runtime.zsh').read_text()
        self.assertNotIn('"$SCRIPT_DIR/game-mode-guard.zsh"', repair)


if __name__ == '__main__':
    unittest.main()
