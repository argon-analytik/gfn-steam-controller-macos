"""Narrow Valve KeyValues editing; no third-party modules or account payload logs."""

import copy
import re
import struct

GFN_NAME = 'GeForce NOW (Steam Controller)'
PROFILE_TITLE = 'GFN - Gamepad + R4 Gyro Aiming'
PROFILE_DESCRIPTION = 'Left stick: movement. Right stick/trackpad: camera. Hold R4 for gentle gyro aiming.'
FINE_GYRO_MODE = 'gyro_to_mouse'
# Verified against Valve's installed UI: R4 = upper right rear grip, mask bit 42.
# The legacy gyro selector uses 24 (a different enum from physical input IDs).
FINE_GYRO_SETTINGS = [
    ('gyro_ratchet_button_mask', str(1 << 42)), ('gyro_button', '24'),
    ('gyro_button_invert', '1'), ('gyro_ratchet_button_requireany_or_all', '0'),
    ('gyro_use_per_controller_preferences', '0'), ('gyro_natural_sensitivity', '50'),
    ('gyro_speed_deadzone', '0'), ('gyro_precision_speed', '0'),
    ('acceleration', '0'), ('trackball', '0'),
]


def parse(text):
    """Keep duplicate group/binding keys, which are significant in Steam layouts."""
    tokens = []
    token_pattern = re.compile(r'\s+|\ufeff|//[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+')
    pos = 0
    for match in token_pattern.finditer(text):
        if match.start() != pos:
            raise ValueError("Malformed VDF token")
        pos = match.end()
        word = match.group()
        if word.isspace() or word == '\ufeff' or word.startswith('//'):
            continue
        if word.startswith('"'):
            word = re.sub(r'\\([\\"nt])', lambda m: {'n': '\n', 't': '\t'}.get(m[1], m[1]), word[1:-1])
            tokens.append(('string', word))
        else:
            tokens.append((word if word in '{}' else 'string', word))
    if pos != len(text):
        raise ValueError("Incomplete VDF token")
    index = 0

    def obj(nested=False):
        nonlocal index
        pairs = []
        while index < len(tokens):
            kind, key = tokens[index]
            index += 1
            if kind == '}':
                if not nested:
                    raise ValueError("Unexpected closing brace")
                return pairs
            if kind != 'string' or index == len(tokens):
                raise ValueError("Missing VDF key or value")
            kind, value = tokens[index]
            index += 1
            if kind == '{':
                value = obj(True)
            elif kind != 'string':
                raise ValueError("Missing VDF value")
            pairs.append((key, value))
        if nested:
            raise ValueError("Unclosed VDF object")
        return pairs

    return obj()


def get(pairs, key, default=None):
    matches = [v for k, v in pairs if k.lower() == key.lower()]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous VDF key: {key}")
    return matches[0] if matches else default


def put(pairs, key, value):
    get(pairs, key)  # Reject ambiguity instead of changing a random duplicate.
    for index, (name, _) in enumerate(pairs):
        if name.lower() == key.lower():
            pairs[index] = (name, value)
            return
    pairs.append((key, value))


def dump(pairs, depth=0):
    def quote(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t') + '"'
    lines = []
    for key, value in pairs:
        indent = '\t' * depth
        if isinstance(value, list):
            lines.extend([indent + quote(key), indent + '{', dump(value, depth + 1).rstrip('\n'), indent + '}'])
        else:
            lines.append(indent + quote(key) + '\t\t' + quote(value))
    return '\n'.join(lines) + '\n'


def gamepad_profile(template, controller_type, account, destination):
    doc = copy.deepcopy(parse(template))
    root = get(doc, 'controller_mappings')
    if get(root, 'controller_type') != 'controller_neptune':
        raise ValueError("Expected the installed Neptune gamepad template")
    presets = [v for k, v in root if k == 'preset']
    if len(presets) != 1:
        raise ValueError("Expected one base action set")
    bindings = get(presets[0], 'group_source_bindings')
    groups = {}
    for key, group in root:
        if key == 'group':
            gid = get(group, 'id')
            if gid in groups:
                raise ValueError("Duplicate group ID")
            groups[gid] = group

    def active(source):
        ids = [key for key, value in bindings if value == source + ' active']
        if len(ids) != 1 or ids[0] not in groups:
            raise ValueError(f"Missing or ambiguous active source: {source}")
        return groups[ids[0]]

    for source, output in [('joystick', '0'), ('right_joystick', '1')]:
        group = active(source)
        if get(group, 'mode') != 'joystick_move':
            raise ValueError(f"Unexpected stick mode: {source}")
        settings = get(group, 'settings', [])
        put(settings, 'output_joystick', output)
        put(group, 'settings', settings)
    dpad = active('dpad')
    if get(dpad, 'mode') != 'dpad':
        raise ValueError("Unexpected D-pad mode")
    inputs = get(dpad, 'inputs')
    def output_bindings(pairs):
        values = []
        for key, value in pairs:
            if isinstance(value, list):
                values.extend(output_bindings(value))
            elif key == 'binding':
                values.append(value)
        return values
    for direction, button in [('dpad_north', 'DPAD_UP'), ('dpad_south', 'DPAD_DOWN'), ('dpad_east', 'DPAD_RIGHT'), ('dpad_west', 'DPAD_LEFT')]:
        # The template must have digital gamepad directions, never camera/mouse.
        if output_bindings(get(inputs, direction, [])) != [f'xinput_button {button}']:
            raise ValueError(f"Unexpected D-pad binding: {direction}")
    if any(value.startswith('gyro ') for _, value in bindings):
        raise ValueError("Template already has a gyro binding; review it first")
    gyro_id = str(max(map(int, groups)) + 1)
    root.append(('group', [
        ('id', gyro_id), ('mode', FINE_GYRO_MODE), ('inputs', []),
        ('settings', copy.deepcopy(FINE_GYRO_SETTINGS)),
    ]))
    bindings.append((gyro_id, 'gyro active'))
    for key, value in [
        ('game', GFN_NAME),
        ('title', PROFILE_TITLE),
        ('description', PROFILE_DESCRIPTION),
        ('controller_type', controller_type), ('revision', '1'),
        ('creator', str(76561197960265728 + int(account))),
        ('progenitor', 'template://controller_neptune_gamepad_fps.vdf'),
        ('url', 'autosave://' + str(destination)), ('export_type', 'personal_local'),
    ]:
        put(root, key, value)
    # Localized template descriptions must not obscure the new profile's title.
    root[:] = [(k, v) for k, v in root if k != 'localization']
    return dump(doc).encode()


def retune_gyro_profile(data):
    """Change only gyro settings and profile metadata, preserving the working layout."""
    doc = parse(data.decode('utf-8-sig'))
    root = get(doc, 'controller_mappings')
    if get(root, 'game') != GFN_NAME or get(root, 'controller_type') not in ['controller_triton', 'controller_neptune']:
        raise ValueError('Not the existing Steam Controller GFN profile')
    preset = get(root, 'preset')
    if not isinstance(preset, list):
        raise ValueError('Expected a single GFN action set')
    bindings = get(preset, 'group_source_bindings', [])
    gyro_ids = [gid for gid, value in bindings if value == 'gyro active']
    groups = [g for k, g in root if k == 'group' and get(g, 'id') in gyro_ids]
    all_gyros = [g for k, g in root if k == 'group' and str(get(g, 'mode')).startswith('gyro_')]
    if len(gyro_ids) != 1 or len(groups) != 1 or all_gyros != groups or get(groups[0], 'mode') not in ['gyro_to_joystick', 'gyro_to_mouse']:
        raise ValueError('Expected exactly one existing analog GFN gyro source')
    before = copy.deepcopy(doc)
    settings = get(groups[0], 'settings', [])
    # A direct mouse gyro must not retain any old stick-output/range settings.
    settings[:] = [(k, v) for k, v in settings
                   if k != 'output_joystick' and not k.startswith(('gyro_to_joystick_', 'gyro_speed_to_joystick_', 'gyro_deflection_to_joystick_'))]
    for key, value in FINE_GYRO_SETTINGS:
        put(settings, key, value)
    put(groups[0], 'mode', FINE_GYRO_MODE)
    put(groups[0], 'settings', settings)
    put(root, 'title', PROFILE_TITLE)
    put(root, 'description', PROFILE_DESCRIPTION)
    if doc == before:
        return data
    put(root, 'revision', str(int(get(root, 'revision', '0')) + 1))
    return dump(doc).encode()


def bind_autosave(data, appid):
    doc = parse(data.decode('utf-8-sig'))
    root = get(doc, 'controller_config')
    if not isinstance(root, list):
        raise ValueError("Missing controller_config")
    put(root, str(appid), [('autosave', '1')])
    return dump(doc).encode()


def shortcut_spans(data):
    """Read binary KeyValues and retain byte spans for exact, narrow replacement."""
    offset = 0

    def cstring():
        nonlocal offset
        end = data.index(b'\0', offset)
        text = data[offset:end].decode('utf-8')
        offset = end + 1
        return text

    def obj():
        nonlocal offset
        rows = []
        while offset < len(data):
            kind = data[offset]
            offset += 1
            if kind == 8:
                return rows
            key = cstring()
            start = offset
            if kind == 0:
                value = obj()
            elif kind == 1:
                value = cstring()
            elif kind == 2:
                value = struct.unpack_from('<I', data, offset)[0]
                offset += 4
            else:
                raise ValueError(f"Unsupported binary VDF type: {kind}")
            rows.append((key, kind, value, start, offset))
        raise ValueError("Unclosed binary VDF object")

    rows = obj()
    if offset != len(data):
        raise ValueError("Trailing binary VDF data")
    return rows


def shortcut_appids(data, appname=GFN_NAME):
    """Return AppIDs for exact-name shortcuts without exposing other entries."""
    root = shortcut_spans(data)
    if len(root) != 1 or root[0][:2] != ('shortcuts', 0):
        raise ValueError("Expected shortcuts root")
    appids = []
    for _, kind, rows, _, _ in root[0][2]:
        if kind != 0:
            raise ValueError("Unexpected shortcut entry")
        values = {k.lower(): v for k, _, v, _, _ in rows}
        if len(values) != len(rows):
            raise ValueError("Duplicate shortcut field")
        if values.get('appname') == appname and isinstance(values.get('appid'), int):
            appids.append(values['appid'])
    return appids


def patch_shortcut(data, appid, runtime, visible=None):
    root = shortcut_spans(data)
    if len(root) != 1 or root[0][:2] != ('shortcuts', 0):
        raise ValueError("Expected shortcuts root")
    candidates = []
    for _, kind, rows, _, _ in root[0][2]:
        if kind != 0:
            raise ValueError("Unexpected shortcut entry")
        values = {k.lower(): v for k, _, v, _, _ in rows}
        if len(values) != len(rows):
            raise ValueError("Duplicate shortcut field")
        if values.get('appid') == int(appid):
            candidates.append((rows, values))
    if len(candidates) != 1:
        raise ValueError("Expected exactly one matching Steam shortcut")
    rows, values = candidates[0]
    accepted_executables = {'"/usr/bin/arch"'}
    if visible is not None:
        accepted_executables.add('"' + str(visible / 'Contents/MacOS/GeForceNOW') + '"')
    if values.get('appname') != GFN_NAME or values.get('exe') not in accepted_executables:
        raise ValueError("Shortcut identity changed")
    executable = str(runtime / 'Contents/MacOS/GeForceNOW')
    if any(c in executable for c in ['"', '\n', '\r', '\0']):
        raise ValueError("Unsupported runtime path")
    edits = {'exe': '"/usr/bin/arch"',
             'startdir': '"' + str(runtime / 'Contents/MacOS') + '"',
             'launchoptions': '-arm64 "' + executable + '"'}
    replacements = []
    for key, kind, _, start, end in rows:
        if key.lower() in edits:
            if kind != 1:
                raise ValueError("Shortcut path is not a string")
            replacements.append((start, end, edits.pop(key.lower()).encode() + b'\0'))
    if edits:
        raise ValueError("Shortcut path fields missing")
    for start, end, replacement in sorted(replacements, reverse=True):
        data = data[:start] + replacement + data[end:]
    return data
