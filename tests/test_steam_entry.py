import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_steam_profile import binary, shortcut

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repair_launch', ROOT / 'repair-steam-launch.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class NativeEntryTests(unittest.TestCase):
    def test_exec_keeps_pid_handles_spaces_and_propagates_exit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            entry = root / 'entry'
            subprocess.run(['cc', '-arch', 'arm64', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'steam-entry.c'), '-o', str(entry)], check=True)
            target = root / 'runtime with spaces'
            target.write_text('#!/bin/sh\nprintf "%s" "$$"\nexit 17\n')
            target.chmod(0o755)
            p = subprocess.Popen([str(entry), str(target)], stdout=subprocess.PIPE, text=True)
            output = p.communicate(timeout=5)[0]
            self.assertEqual(output, str(p.pid))
            self.assertEqual(p.returncode, 17)
            for args, expected in [([], 64), (['relative'], 64), ([str(root/'absent')], 126)]:
                r = subprocess.run([str(entry), *args], capture_output=True, timeout=5)
                self.assertEqual(r.returncode, expected)
            runtime = root / 'GFN.app/Contents/MacOS/GeForceNOW'
            runtime.parent.mkdir(parents=True)
            runtime.write_text('#!/bin/sh\nexit 17\n')
            runtime.chmod(0o755)
            self.assertEqual(subprocess.run([str(entry), str(runtime)], capture_output=True).returncode, 78)
            bridge = root / 'GFN.app/Contents/Frameworks/libGeronimo.original.dylib'
            bridge.parent.mkdir()
            bridge.write_bytes(b'test marker')
            self.assertEqual(subprocess.run([str(entry), str(runtime)], capture_output=True).returncode, 17)

    def test_failed_shortcut_write_restores_existing_helper(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td).resolve()
            runtime = home / 'Library/Application Support/gfn-steam-controller-macos/runtime/GFN.app'
            entry = runtime.parent / 'steam-gfn-entry'
            entry.parent.mkdir(parents=True)
            entry.write_bytes(b'previous helper')
            entry.chmod(0o751)
            shortcut_file = home / 'Library/Application Support/Steam/userdata/1/config/shortcuts.vdf'
            shortcut_file.parent.mkdir(parents=True)
            original = binary(shortcut())
            shortcut_file.write_bytes(original)
            def command(args, **kwargs):
                if args[0] == 'cc':
                    Path(args[-1]).write_bytes(b'candidate helper')
                return subprocess.CompletedProcess(args, 0)
            real_write = repair.config.atomic_write
            def write(path, data, mode=0o600):
                if path == shortcut_file:
                    raise OSError('simulated write failure')
                real_write(path, data, mode)
            with patch.object(Path, 'home', return_value=home), \
                 patch.object(repair.sys, 'argv', ['repair', '--account', '1', '--appid', '3000000000', '--apply']), \
                 patch.object(repair.config, 'stopped'), patch.object(repair.config, 'verify_runtime'), \
                 patch.object(repair.subprocess, 'run', side_effect=command), \
                 patch.object(repair.subprocess, 'check_output', return_value='arm64'), \
                 patch.object(repair.config, 'atomic_write', side_effect=write), \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):
                repair.main()
            self.assertEqual(entry.read_bytes(), b'previous helper')
            self.assertEqual(entry.stat().st_mode & 0o777, 0o751)
            self.assertEqual(shortcut_file.read_bytes(), original)
