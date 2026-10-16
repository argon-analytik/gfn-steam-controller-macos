from pathlib import Path
import json
import subprocess
import tempfile
import unittest

GUARD = Path(__file__).resolve().parents[1] / 'game-mode-guard.zsh'


class GameModeGuardTests(unittest.TestCase):
    def run_guard(self, policy='auto', failure=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root/'state.json'
            state.write_text(json.dumps({'policy': policy, 'failure': failure, 'calls': []}))
            tool = root/'gamepolicyctl'
            tool.write_text('''#!/usr/bin/env python3
from pathlib import Path
import json, sys
p=Path(__file__).with_name('state.json');d=json.loads(p.read_text());a=sys.argv[1:]
d['calls'].append(a);p.write_text(json.dumps(d))
if a == ['game-mode', 'set', 'off']:
    if d['failure']=='set':sys.exit(1)
    if d['failure']!='readback':d['policy']='off'
    p.write_text(json.dumps(d));sys.exit(0)
assert a == ['game-mode','status']
if d['policy']=='off':print('Game mode is forced always off.')
elif d['policy']=='auto':print('Game mode enablement policy is currently automatic.')
else:print('Unrecognized policy format')
''')
            tool.chmod(0o755)
            result = subprocess.run(['/bin/zsh', '-c',
                'source "$1"; shift; gfn_force_game_mode_off "$@"', 'guard-test', str(GUARD), str(tool)],
                capture_output=True, text=True, timeout=10)
            return result, json.loads(state.read_text())

    def test_automatic_is_disabled_and_read_back(self):
        r, state = self.run_guard()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(state['policy'], 'off')
        self.assertEqual(state['calls'], [['game-mode','status'], ['game-mode','set','off'], ['game-mode','status']])

    def test_already_off_is_read_only(self):
        r, state = self.run_guard('off')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(state['calls'], [['game-mode','status']])

    def test_unknown_policy_or_failed_change_stops_launch(self):
        for policy, failure in [('unknown', None), ('auto','set'), ('auto','readback')]:
            with self.subTest(policy=policy, failure=failure):
                r, state = self.run_guard(policy, failure)
                self.assertNotEqual(r.returncode, 0)
                if policy=='unknown':self.assertEqual(state['calls'], [['game-mode','status']])
