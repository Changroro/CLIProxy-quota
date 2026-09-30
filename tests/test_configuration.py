import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli_proxy_quota import configuration


class ConfigurationTest(unittest.TestCase):
    def test_theme_save_preserves_file_key_and_does_not_persist_environment_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            configuration, "CONFIG_DIR", Path(directory)
        ), patch.object(configuration, "CONFIG_PATH", Path(directory) / "config.json"), patch.dict(
            os.environ, {"CLIPROXY_MANAGEMENT_KEY": "environment-secret"}, clear=True
        ):
            configuration.save_settings({"management_key": "file-secret", "theme": "light"})
            configuration.save_theme("dark")
            self.assertEqual(configuration.load_settings()["theme"], "dark")
            self.assertEqual(configuration.load_settings()["management_key"], "environment-secret")
            raw = configuration.CONFIG_PATH.read_text()
            self.assertNotIn("environment-secret", raw)
            self.assertEqual(json.loads(raw)["management_key"], "file-secret")
            self.assertEqual(configuration.CONFIG_PATH.stat().st_mode & 0o777, 0o600)

    def test_missing_key_and_management_path_are_rejected(self):
        with patch.object(configuration, "stored_settings", return_value={}), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                configuration.load_settings()
        with patch.object(configuration, "stored_settings", return_value={
            "base_url": "http://localhost:8317/v8/management", "management_key": "test"
        }), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                configuration.load_settings()
