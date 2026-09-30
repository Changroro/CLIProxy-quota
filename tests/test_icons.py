import unittest
from pathlib import Path
import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf


class ServiceIconTest(unittest.TestCase):
    def test_symbolic_logos_have_transparent_space_around_the_glyph(self):
        assets = Path(__file__).resolve().parents[1] / "assets"
        for provider in ("codex", "claude"):
            icon = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(assets / f"{provider}-symbolic.svg"), 32, 32, True)
            self.assertTrue(icon.get_has_alpha(), provider)
            pixels = icon.get_pixels()
            channels, stride = icon.get_n_channels(), icon.get_rowstride()
            transparent = sum(pixels[y * stride + x * channels + channels - 1] < 32
                              for y in range(icon.get_height()) for x in range(icon.get_width()))
            self.assertGreater(transparent, icon.get_width() * icon.get_height() // 5, provider)
