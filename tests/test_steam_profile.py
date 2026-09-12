import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from steam_profile import bind_autosave, dump, gamepad_profile, get, parse, patch_shortcut, shortcut_spans, put, retune_gyro_profile


def template():
    directions = [('dpad_north', 'DPAD_UP'), ('dpad_south', 'DPAD_DOWN'),
                  ('dpad_west', 'DPAD_LEFT'), ('dpad_east', 'DPAD_RIGHT')]
    return [('controller_mappings', [
        ('controller_type', 'controller_neptune'),
        ('group', [('id', '2'), ('mode', 'joystick_move'), ('settings', [('deadzone', '123')])]),
        ('group', [('id', '7'), ('mode', 'joystick_move')]),
        ('group', [('id', '9'), ('mode', 'dpad'), ('inputs', [
            (key, [('binding', 'xinput_button ' + value)]) for key, value in directions])]),
        ('preset', [('group_source_bindings', [('2', 'joystick active'),
            ('7', 'right_joystick active'), ('9', 'dpad active')])]),
    ])]


def binary(rows):
    output = b''
    for key, value in rows:
        if isinstance(value, list):
            output += b'\0' + key.encode() + b'\0' + binary(value)
        elif isinstance(value, int):
            output += b'\2' + key.encode() + b'\0' + struct.pack('<I', value)
        else:
            output += b'\1' + key.encode() + b'\0' + value.encode() + b'\0'
    return output + b'\10'


def shortcut():
    return [('shortcuts', [('0', [
        ('appid', 3000000000), ('AppName', 'GeForce NOW (Steam Controller)'),
        ('Exe', '"/usr/bin/arch"'), ('StartDir', 'old dir'), ('LaunchOptions', 'old options'),
        ('tags', [('0', 'Personal')]), ('AllowOverlay', 0), ('AllowDesktopConfig', 0),
    ]), ('1', [('appid', 3000000001), ('AppName', 'Unrelated'), ('Exe', '/other')])])]


class SteamProfileTests(unittest.TestCase):
    def test_roundtrip_duplicates_unicode_escapes(self):
        rows = [('group', [('binding', 'a'), ('binding', 'b')]),
                ('group', [('title', 'Camera "Gyro"\\Path\nÅ')])]
        self.assertEqual(parse('\ufeff// comment\n' + dump(rows)), rows)

    def test_reject_malformed_text(self):
        for text in ['"key"', '"key" {', '}', '"unclosed', '"key" }']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(text)

    def test_reject_ambiguous_single_key(self):
        with self.assertRaises(ValueError):
            get([('ID', '1'), ('id', '2')], 'id')

    def test_axes_and_dpad_keep_distinct_outputs(self):
        original = template()
        result = parse(gamepad_profile(dump(original), 'controller_triton', 1, Path('/tmp/test')).decode())
        root = get(result, 'controller_mappings')
        groups = {get(g, 'id'): g for k, g in root if k == 'group'}
        self.assertEqual(get(get(groups['2'], 'settings'), 'output_joystick'), '0')
        self.assertEqual(get(get(groups['7'], 'settings'), 'output_joystick'), '1')
        self.assertEqual(get(get(groups['2'], 'settings'), 'deadzone'), '123')
        self.assertEqual(groups['9'], get(original, 'controller_mappings')[3][1])
        self.assertEqual(get(root, 'controller_type'), 'controller_triton')
        self.assertEqual(get(root, 'title'), 'GFN - Gamepad + R4 Gyro Aiming')

    def test_gyro_is_only_r4_held_and_uses_fine_sensitivity(self):
        result = parse(gamepad_profile(dump(template()), 'controller_triton', 1, Path('/tmp/test')).decode())
        root = get(result, 'controller_mappings')
        gyro = next(g for k, g in root if k == 'group' and get(g, 'mode') == 'gyro_to_mouse')
        settings = get(gyro, 'settings')
        mask = int(get(settings, 'gyro_ratchet_button_mask'))
        self.assertEqual(mask, 1 << 42)
        self.assertEqual(mask & ((1 << 24) | (1 << 0) | (1 << 25) | (1 << 1)), 0)
        self.assertEqual(get(settings, 'gyro_button'), '24')
        self.assertEqual(get(settings, 'gyro_button_invert'), '1')
        self.assertIsNone(get(settings, 'output_joystick'))
        self.assertIsNone(get(settings, 'gyro_to_joystick_enable_angle_catchup'))
        self.assertEqual(get(settings, 'gyro_speed_deadzone'), '0')
        self.assertEqual(get(settings, 'gyro_precision_speed'), '0')
        self.assertEqual(get(settings, 'trackball'), '0')
        self.assertEqual(get(gyro, 'inputs'), [])
        self.assertEqual(get(settings, 'gyro_use_per_controller_preferences'), '0')
        self.assertEqual(get(settings, 'gyro_natural_sensitivity'), '50')
        self.assertEqual(get(settings, 'acceleration'), '0')
        preset = get(root, 'preset')
        self.assertIn((get(gyro, 'id'), 'gyro active'), get(preset, 'group_source_bindings'))

    def test_retune_preserves_all_non_gyro_controls(self):
        original = parse(gamepad_profile(dump(template()), 'controller_triton', 1, Path('/tmp/test')).decode())
        root = get(original, 'controller_mappings')
        gyro = next(g for k, g in root if k == 'group' and get(g, 'mode') == 'gyro_to_mouse')
        put(gyro, 'mode', 'gyro_to_joystick')
        put(gyro, 'settings', [('gyro_ratchet_button_mask', '16777217'), ('gyro_button', '46'), ('output_joystick', '1'),
                              ('gyro_to_joystick_out_min', '5000'), ('gyro_speed_to_joystick_max', '100'),
                              ('gyro_speed_deadzone', '36'), ('gyro_precision_speed', '75')])
        put(root, 'title', 'GFN - Gamepad + Gyro on R2')
        root.append(('custom_user_setting', 'preserve me'))
        root.append(('group', [('id', '100'), ('mode', 'switches'), ('inputs', [('binding', 'xinput_button A')])]))
        data = dump(original).encode()
        changed = parse(retune_gyro_profile(data).decode())
        after = get(changed, 'controller_mappings')
        def other_fields(rows):
            return [(k, v) for k, v in rows if k not in ['title', 'description', 'revision']
                    and not (k == 'group' and str(get(v, 'mode')).startswith('gyro_'))]
        self.assertEqual(other_fields(root), other_fields(after))
        self.assertEqual(int(get(after, 'revision')), int(get(root, 'revision')) + 1)
        adjusted = next(g for k, g in after if k == 'group' and get(g, 'mode') == 'gyro_to_mouse')
        self.assertEqual(get(get(adjusted, 'settings'), 'gyro_ratchet_button_mask'), str(1 << 42))
        self.assertIsNone(get(get(adjusted, 'settings'), 'output_joystick'))
        self.assertIsNone(get(get(adjusted, 'settings'), 'gyro_to_joystick_out_min'))
        self.assertIsNone(get(get(adjusted, 'settings'), 'gyro_speed_to_joystick_max'))
        self.assertEqual(get(get(adjusted, 'settings'), 'gyro_speed_deadzone'), '0')
        self.assertEqual(get(get(adjusted, 'settings'), 'gyro_precision_speed'), '0')
        self.assertEqual(retune_gyro_profile(retune_gyro_profile(data)), retune_gyro_profile(data))

    def test_retune_rejects_foreign_or_ambiguous_profile(self):
        data = gamepad_profile(dump(template()), 'controller_triton', 1, Path('/tmp/test'))
        for case in ['other-game', 'second-gyro', 'missing-gyro', 'unsupported-gyro']:
            doc = parse(data.decode())
            root = get(doc, 'controller_mappings')
            gyro = next(g for k, g in root if k == 'group' and get(g, 'mode') == 'gyro_to_mouse')
            if case == 'other-game': put(root, 'game', 'Other game')
            elif case == 'second-gyro': root.append(('group', copy.deepcopy(gyro)))
            elif case == 'unsupported-gyro': put(gyro, 'mode', 'gyro_to_joystick_deflection')
            else: put(get(root, 'preset'), 'group_source_bindings', [('2', 'joystick active')])
            with self.subTest(case=case), self.assertRaises(ValueError):
                retune_gyro_profile(dump(doc).encode())

    def test_refuse_wrong_or_missing_source(self):
        for field, bad in [('mode', 'joystick_mouse'), ('id', '12')]:
            doc = template()
            group = get(doc, 'controller_mappings')[1][1]
            group[:] = [(k, bad if k == field else v) for k, v in group]
            with self.assertRaises(ValueError):
                gamepad_profile(dump(doc), 'controller_triton', 1, Path('/tmp/test'))

    def test_refuse_extra_dpad_keyboard_mapping(self):
        doc = template()
        dpad = get(doc, 'controller_mappings')[3][1]
        get(get(dpad, 'inputs'), 'dpad_north').append(('binding', 'key_press UP'))
        with self.assertRaises(ValueError):
            gamepad_profile(dump(doc), 'controller_triton', 1, Path('/tmp/test'))

    def test_autosave_preserves_other_game(self):
        data = b'"controller_config" { "12" { "workshop" "34" } "99" { "template" "old.vdf" } }'
        updated = get(parse(bind_autosave(data, 99).decode()), 'controller_config')
        self.assertEqual(get(updated, '12'), [('workshop', '34')])
        self.assertEqual(get(updated, '99'), [('autosave', '1')])

    def test_nonsteam_profile_uses_name_key(self):
        data = b'"controller_config" { "12" { "workshop" "34" } }'
        updated = get(parse(bind_autosave(data, 'geforce now (steam controller)').decode()), 'controller_config')
        self.assertEqual(get(updated, 'geforce now (steam controller)'), [('autosave', '1')])
        self.assertEqual(get(updated, '12'), [('workshop', '34')])

    def test_binary_changes_only_two_path_strings(self):
        rows = shortcut()
        before = binary(rows)
        runtime = Path('/tmp/Test Person/Application Support/GFN.app')
        changed = patch_shortcut(before, 3000000000, runtime)
        expected = copy.deepcopy(rows)
        entry = expected[0][1][0][1]
        entry[3] = ('StartDir', '"' + str(runtime/'Contents/MacOS') + '"')
        entry[4] = ('LaunchOptions', '-arm64 "' + str(runtime/'Contents/MacOS/GeForceNOW') + '"')
        self.assertEqual(changed, binary(expected))
        self.assertEqual(patch_shortcut(changed, 3000000000, runtime), changed)

    def test_binary_accepts_new_direct_app_shortcut_and_routes_through_arch(self):
        rows = shortcut()
        visible = Path('/tmp/Applications/GeForceNOW-Steam-Controller.app')
        rows[0][1][0][1][2] = ('Exe', '"' + str(visible/'Contents/MacOS/GeForceNOW') + '"')
        changed = shortcut_spans(patch_shortcut(binary(rows), 3000000000, Path('/tmp/runtime.app'), visible))
        entry = {key.lower(): value for key, _, value, _, _ in changed[0][2][0][2]}
        self.assertEqual(entry['exe'], '"/usr/bin/arch"')
        self.assertEqual(entry['launchoptions'], '-arm64 "/tmp/runtime.app/Contents/MacOS/GeForceNOW"')

    def test_binary_refuses_wrong_identity_or_duplicate(self):
        rows = shortcut()
        rows[0][1][0][1].append(('Exe', 'untrusted'))
        with self.assertRaises(ValueError):
            patch_shortcut(binary(rows), 3000000000, Path('/tmp/a'))
        with self.assertRaises(ValueError):
            patch_shortcut(binary(shortcut()), 3000000001, Path('/tmp/a'))

    def test_binary_refuses_incomplete_or_extra_data(self):
        data = binary(shortcut())
        for bad in [data[:-1], data+b'\10', b'\7unexpected\0\10']:
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                shortcut_spans(bad)


if __name__ == '__main__':
    unittest.main()
