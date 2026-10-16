import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io

spec = importlib.util.spec_from_file_location('configure_steam', Path(__file__).resolve().parents[1]/'configure-steam.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfigurationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.visible, self.runtime, self.launcher, self.backup = [root/name for name in ['Visible.app', 'Runtime.app', 'Launcher.app', 'backup']]
        for path in [self.visible, self.launcher, self.backup]:
            path.mkdir()
        (self.visible/'marker').write_text('native-gfn')
        (self.launcher/'marker').write_text('new-launcher')
        self.existing, self.new = root/'existing.vdf', root/'new.vdf'
        self.existing.write_bytes(b'original')
        self.originals = {self.existing: b'original', self.new: None}
        self.changes = {self.existing: b'new', self.new: b'created'}

    def run_transaction(self, preflight=lambda: None, verify=lambda _: None):
        return module.install_transaction(self.visible, self.runtime, self.launcher,
            self.changes, self.originals, self.backup, preflight=preflight, verify=verify)

    def assert_original_app(self):
        self.assertEqual((self.visible/'marker').read_text(), 'native-gfn')
        self.assertFalse(self.runtime.exists())
        self.assertFalse(self.visible.with_name('Visible.app.staging-backup').exists())

    def test_install_preserves_runtime_and_installs_all_files(self):
        self.assertTrue(self.run_transaction())
        self.assertEqual((self.runtime/'marker').read_text(), 'native-gfn')
        self.assertEqual((self.visible/'marker').read_text(), 'new-launcher')
        for path, data in self.changes.items():
            self.assertEqual(path.read_bytes(), data)

    def test_preflight_failure_changes_nothing(self):
        def fail():
            raise RuntimeError('Steam running')
        with self.assertRaises(RuntimeError):
            self.run_transaction(preflight=fail)
        self.assert_original_app()
        self.assertEqual(self.existing.read_bytes(), b'original')
        self.assertFalse(self.new.exists())

    def test_drift_before_first_write_is_not_rolled_back(self):
        def concurrent_edit():
            self.existing.write_bytes(b'foreign edit')
        with self.assertRaisesRegex(RuntimeError, 'changed during'):
            self.run_transaction(preflight=concurrent_edit)
        self.assert_original_app()
        self.assertEqual(self.existing.read_bytes(), b'foreign edit')
        self.assertFalse(self.new.exists())

    def test_verification_failure_restores_existing_and_removes_only_new_file(self):
        def fail(_):
            raise RuntimeError('verification failed')
        with self.assertRaises(RuntimeError):
            self.run_transaction(verify=fail)
        self.assert_original_app()
        self.assertEqual(self.existing.read_bytes(), b'original')
        self.assertFalse(self.new.exists())

    def test_rollback_preserves_concurrent_edit(self):
        def edit_then_fail(_):
            self.existing.write_bytes(b'foreign edit')
            raise RuntimeError('verification failed')
        with self.assertRaisesRegex(RuntimeError, 'Concurrent edits preserved'):
            self.run_transaction(verify=edit_then_fail)
        self.assert_original_app()
        self.assertEqual(self.existing.read_bytes(), b'foreign edit')
        self.assertFalse(self.new.exists())

    def test_update_rollback_keeps_existing_runtime_and_previous_launcher(self):
        self.runtime.mkdir()
        (self.runtime/'marker').write_text('native-gfn')
        (self.visible/'marker').write_text('old-launcher')
        def fail(_):
            raise RuntimeError('verification failed')
        with self.assertRaises(RuntimeError):
            self.run_transaction(verify=fail)
        self.assertEqual((self.runtime/'marker').read_text(), 'native-gfn')
        self.assertEqual((self.visible/'marker').read_text(), 'old-launcher')
        self.assertEqual(self.existing.read_bytes(), b'original')


class LauncherIdentityTests(unittest.TestCase):
    def test_exact_bundle_and_route(self):
        identity = json.loads((Path(__file__).resolve().parents[1]/'launcher/identity.json').read_text())
        info = {'CFBundleIdentifier': identity['bundle_id'], 'CFBundleExecutable': identity['executable'],
                'SteamGameID': '123', 'GFNRuntimePath': '/tmp/runtime.app'}
        module.validate_launcher_info(info, '123', Path('/tmp/runtime.app'))
        for key, wrong in [('CFBundleIdentifier', 'io.github.wrong-product.launcher'),
                           ('CFBundleIdentifier', 'io.github.other-product.launcher'),
                           ('CFBundleExecutable', 'WrongHelper'), ('SteamGameID', '124'),
                           ('GFNRuntimePath', '/Applications/GeForceNOW.app')]:
            with self.subTest(key=key, value=wrong), self.assertRaises(ValueError):
                module.validate_launcher_info({**info, key: wrong}, '123', Path('/tmp/runtime.app'))


class GyroUpdateTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.paths = [self.root/'one.vdf', self.root/'two.vdf']
        self.original = b'''"controller_mappings" {
            "game" "GeForce NOW (Steam Controller)" "controller_type" "controller_triton"
            "revision" "1" "group" { "id" "1" "mode" "gyro_to_joystick"
                "settings" { "gyro_ratchet_button_mask" "16777217" } }
            "preset" { "group_source_bindings" { "1" "gyro active" } }
        }'''
        for path in self.paths: path.write_bytes(self.original)

    def test_running_steam_stops_before_backup_or_write(self):
        with patch.object(module.Path, 'home', return_value=self.root), \
             patch.object(module, 'stopped', side_effect=RuntimeError('Steam running')), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            module.retune_profiles(self.paths, True)
        self.assertFalse((self.root/'Library').exists())
        for path in self.paths: self.assertEqual(path.read_bytes(), self.original)

    def test_partial_profile_write_restores_originals(self):
        real_write = module.atomic_write
        def fail_second(path, data, mode=0o600):
            if path == self.paths[1] and data != self.original:
                raise OSError('simulated second profile failure')
            real_write(path, data, mode)
        with patch.object(module.Path, 'home', return_value=self.root), \
             patch.object(module, 'stopped'), patch.object(module, 'atomic_write', side_effect=fail_second), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):
            module.retune_profiles(self.paths, True)
        for path in self.paths: self.assertEqual(path.read_bytes(), self.original)
        self.assertEqual(len(list(self.root.rglob('files.json'))), 1)
        self.assertEqual(len(list(self.root.rglob('receipt.json'))), 0)


if __name__ == '__main__':
    unittest.main()
