import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('duplicates', ROOT/'repair-controller-duplicates.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
exclude = module.exclude_apple_duplicate


class DuplicateControllerTests(unittest.TestCase):
    def test_add_only_one_key_and_preserve_unrelated_text_and_line_endings(self):
        original = '"InstallConfigStore"\r\n{\r\n\t"unrelated"\t"value"\r\n}\r\n'
        updated = exclude(original)
        self.assertEqual(updated.replace('\r\n\t"controller_blacklist"\t\t"05ac/0004"', ''), original)
        self.assertEqual(exclude(updated), updated)

    def test_existing_exclusions_preserved(self):
        original = '"InstallConfigStore" { "controller_blacklist" "1234/ABCD" "other" "kept" }'
        updated = exclude(original)
        self.assertEqual(updated, original.replace('1234/ABCD', '1234/ABCD,05ac/0004'))
        self.assertEqual(exclude(updated), updated)

    def test_ambiguous_or_unexpected_settings_rejected(self):
        for text in ['"other" {}',
                     '"InstallConfigStore" { "controller_blacklist" "*" }',
                     '"InstallConfigStore" { "nested" { "controller_blacklist" "1234/5678" } }',
                     '"InstallConfigStore" { "controller_blacklist" "" "controller_blacklist" "" }']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                exclude(text)
