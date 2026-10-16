"""Exercise update repair transactions without touching installed applications."""
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.tools = self.root / 'tools'
        (self.tools / 'lib').mkdir(parents=True)
        for name in ('ensure-runtime.zsh', 'lib/app-transaction.zsh'):
            shutil.copyfile(ROOT / name, self.tools / name)
        self.runtime = self.root / 'private runtime.app'
        (self.runtime / 'Contents/MacOS').mkdir(parents=True)
        (self.runtime / 'Contents/Frameworks').mkdir()
        (self.runtime / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleShortVersionString': '999.0.0', 'CFBundleIdentifier': 'com.nvidia.gfnpc.mall'}))
        exe = self.runtime / 'Contents/MacOS/GeForceNOW'
        exe.write_text('original executable')
        exe.chmod(0o755)
        self.library = self.runtime / 'Contents/Frameworks/libGeronimo.dylib'
        self.library.write_text('unpatched')
        self.marker = self.library.with_name('libGeronimo.original.dylib')
        self.script('verify.zsh', '''
[[ -f "$1/Contents/Frameworks/libGeronimo.original.dylib" ]] || exit 3
[[ "$(cat "$1/Contents/Frameworks/libGeronimo.dylib")" == patched ]]
''')
        self.script('build.zsh', '''
cp -R "$1" "$2"
print patched > "$2/Contents/Frameworks/libGeronimo.dylib"
touch "$2/Contents/Frameworks/libGeronimo.original.dylib"
''')
        self.script('reset-gfn-container.zsh', 'exit 0\n')
        self.script('game-mode-guard.zsh', 'exit 0\n')

    def script(self, name, text):
        path = self.tools / name
        path.write_text('#!/bin/zsh\nset -eu\n' + text)
        path.chmod(0o755)

    def run_repair(self):
        return subprocess.run(['/bin/zsh', str(self.tools/'ensure-runtime.zsh'), str(self.runtime)],
                              capture_output=True, text=True, timeout=20)

    def test_repair_then_repeated_start_does_not_build_or_stop_apps(self):
        result = self.run_repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.library.read_text().strip(), 'patched')
        self.script('build.zsh', 'exit 99\n')
        self.script('reset-gfn-container.zsh', 'exit 99\n')
        self.assertEqual(self.run_repair().returncode, 0)

    def test_unsupported_update_and_active_game_preserve_original(self):
        original_build = (self.tools/'build.zsh').read_text()
        self.script('build.zsh', 'exit 3\n')
        self.assertNotEqual(self.run_repair().returncode, 0)
        self.assertEqual(self.library.read_text(), 'unpatched')
        (self.tools/'build.zsh').write_text(original_build)
        self.script('reset-gfn-container.zsh', 'exit 1\n')
        self.assertNotEqual(self.run_repair().returncode, 0)
        self.assertEqual(self.library.read_text(), 'unpatched')
        self.assertFalse(self.marker.exists())

    def test_failed_installed_verification_restores_original(self):
        self.script('verify.zsh', '''
[[ "$1" == *'/.gfn-repair.'* ]] || exit 3
[[ -f "$1/Contents/Frameworks/libGeronimo.original.dylib" ]]
''')
        self.assertNotEqual(self.run_repair().returncode, 0)
        self.assertEqual(self.library.read_text(), 'unpatched')
        self.assertFalse(self.marker.exists())

    def test_changed_runtime_is_not_replaced(self):
        self.script('build.zsh', (self.tools/'build.zsh').read_text() +
                    '\nprint concurrent-update > "$1/Contents/Frameworks/libGeronimo.dylib"\n')
        self.assertNotEqual(self.run_repair().returncode, 0)
        self.assertEqual(self.library.read_text().strip(), 'concurrent-update')
        self.assertFalse(self.marker.exists())

    def test_damaged_custom_build_is_not_automatically_replaced(self):
        self.marker.touch()
        self.script('build.zsh', 'exit 99\n')
        result = self.run_repair()
        self.assertEqual(result.returncode, 1)
        self.assertIn('manual repair', result.stderr)
        self.assertEqual(self.library.read_text(), 'unpatched')
