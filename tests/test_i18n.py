import ast
import string
import unittest
from pathlib import Path
from cli_proxy_quota import i18n


class TranslationTest(unittest.TestCase):
    def test_catalog_coverage_and_interpolation_match_both_languages(self):
        formatter = string.Formatter()
        for source, english in i18n.ENGLISH.items():
            fields = lambda text: {field for _, field, _, _ in formatter.parse(text) if field is not None}
            self.assertEqual(fields(source), fields(english), source)
            self.assertTrue(english)
        for path in Path(i18n.__file__).parent.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        self.assertIn(node.args[0].value, i18n.ENGLISH)
        previous = i18n.LANGUAGE
        try:
            i18n.set_language("en")
            self.assertEqual(i18n.t("저장"), "Save")
            self.assertEqual(i18n.t("{v0}월 {v1}일", v0=10, v1=7), "10/7")
            with self.assertRaises(KeyError):
                i18n.t("untranslated")
            i18n.set_language("ko")
            self.assertEqual(i18n.t("저장"), "저장")
            with self.assertRaises(ValueError):
                i18n.set_language("unknown")
        finally:
            i18n.set_language(previous)
